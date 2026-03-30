import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import get_db, get_redis, get_kis_client, get_naver_client, get_broker, get_risk_manager, get_notifier, get_trading_guard
from app.execution.trading_guard import TradingGuard
from app.execution.broker import BrokerClient
from app.execution.risk_manager import RiskManager
from app.services.kis_api import KISClient
from app.services.naver_news import NaverNewsClient
from app.services.notification import NotificationService
from app.trading.loop import run_trading_cycle, save_portfolio_snapshot
from app.trading.monitor import check_positions

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/run-cycle")
async def api_run_cycle(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
    naver_client: NaverNewsClient = Depends(get_naver_client),
    broker: BrokerClient = Depends(get_broker),
    risk_mgr: RiskManager = Depends(get_risk_manager),
    notifier: NotificationService = Depends(get_notifier),
):
    """Execute one full trading cycle: collect → analyze → signal → execute → snapshot."""
    return await run_trading_cycle(
        pool=pool, redis=redis, kis_client=kis_client, naver_client=naver_client,
        broker=broker, risk_mgr=risk_mgr, notifier=notifier,
    )


@router.post("/snapshot")
async def api_snapshot(pool: asyncpg.Pool = Depends(get_db)):
    """Save portfolio snapshot."""
    return await save_portfolio_snapshot(pool=pool)


@router.post("/monitor")
async def api_monitor(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    broker: BrokerClient = Depends(get_broker),
    risk_mgr: RiskManager = Depends(get_risk_manager),
    notifier: NotificationService = Depends(get_notifier),
):
    """Check all positions for stop-loss / take-profit triggers."""
    return await check_positions(pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr, notifier=notifier)


@router.get("/status")
async def api_trading_status(pool: asyncpg.Pool = Depends(get_db)):
    """Get latest portfolio snapshot as trading status."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT time, total_value, cash, invested, daily_pnl, daily_return,
                   cumulative_return, mdd, positions_count
            FROM portfolio_snapshots
            ORDER BY time DESC
            LIMIT 1
            """
        )

    if not row:
        return {"status": "no_snapshots", "message": "아직 스냅샷이 없습니다. /trading/run-cycle을 실행하세요."}

    return {
        "time": row["time"].isoformat(),
        "total_value": float(row["total_value"]),
        "cash": float(row["cash"]),
        "invested": float(row["invested"]),
        "daily_pnl": float(row["daily_pnl"]) if row["daily_pnl"] else 0,
        "daily_return_pct": round(float(row["daily_return"]) * 100, 2) if row["daily_return"] else 0,
        "cumulative_return_pct": round(float(row["cumulative_return"]) * 100, 2) if row["cumulative_return"] else 0,
        "mdd_pct": round(float(row["mdd"]) * 100, 2) if row["mdd"] else 0,
        "positions_count": row["positions_count"],
    }


@router.post("/kill-switch/activate")
async def api_kill_switch_activate(
    guard: TradingGuard = Depends(get_trading_guard),
    notifier: NotificationService = Depends(get_notifier),
):
    """Activate kill switch — blocks ALL new orders immediately."""
    await guard.activate_kill_switch("수동 활성화 (operator)")
    await notifier.alert("🚨 [킬 스위치 활성화] 수동 조작으로 모든 신규 주문이 차단되었습니다.")
    return {"status": "activated", "message": "킬 스위치 활성화 — 모든 신규 주문 차단"}


@router.post("/kill-switch/deactivate")
async def api_kill_switch_deactivate(guard: TradingGuard = Depends(get_trading_guard)):
    """Deactivate kill switch — requires manual operator action."""
    await guard.deactivate_kill_switch()
    return {"status": "deactivated", "message": "킬 스위치 해제 — 신규 주문 허용"}


@router.get("/kill-switch/status")
async def api_kill_switch_status(guard: TradingGuard = Depends(get_trading_guard)):
    """Get current kill switch and trading guard status."""
    active = await guard.is_kill_switch_active()
    _, daily_loss = await guard.check_daily_loss()
    session_ok, session_msg, session_info = guard.is_trading_session()
    broker_failures = await guard.get_broker_failure_count()

    return {
        "kill_switch": "active" if active else "inactive",
        "daily_loss_pct": round(daily_loss * 100, 2),
        "session": {"allowed": session_ok, "message": session_msg, **session_info},
        "broker_failures": broker_failures,
        "broker_limit": settings.risk_broker_max_failures,
    }


@router.post("/reconcile")
async def api_eod_reconcile(
    pool: asyncpg.Pool = Depends(get_db),
    kis_client: KISClient = Depends(get_kis_client),
    notifier: NotificationService = Depends(get_notifier),
):
    """End-of-day broker reconciliation (v1.31 A-3).

    Compares internal positions/cash/orders with BROKER ledger via KIS API.
    Should be called daily after market close (via n8n WF or manually).
    """
    from app.services.audit import log_event

    mismatches = []
    async with pool.acquire() as conn:
        # 1. Check for orphaned orders (SUBMITTED/ACKED but not resolved)
        orphaned = await conn.fetch(
            """
            SELECT order_id, stock_code, side, quantity, status
            FROM orders
            WHERE status IN ('SUBMITTED', 'ACKED', 'PARTIALLY_FILLED', 'UNKNOWN')
              AND time > CURRENT_DATE - INTERVAL '1 day'
            """
        )
        for o in orphaned:
            mismatches.append({
                "type": "orphaned_order",
                "order_id": o["order_id"],
                "stock_code": o["stock_code"],
                "status": o["status"],
            })

        # 2. Check positions with zero or negative quantity
        bad_positions = await conn.fetch(
            "SELECT stock_code, quantity, avg_price FROM portfolio_positions WHERE quantity <= 0"
        )
        for p in bad_positions:
            mismatches.append({
                "type": "invalid_position",
                "stock_code": p["stock_code"],
                "quantity": p["quantity"],
            })

        # 3. Check cash consistency (snapshot vs computed)
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash, invested FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )
        positions = await conn.fetch(
            "SELECT SUM(quantity * avg_price) as total_invested FROM portfolio_positions WHERE quantity > 0"
        )
        if snapshot and positions:
            snap_invested = float(snapshot["invested"])
            actual_invested = float(positions[0]["total_invested"] or 0)
            diff = abs(snap_invested - actual_invested)
            if diff > 1000:  # 1000원 이상 차이
                mismatches.append({
                    "type": "cash_mismatch",
                    "snapshot_invested": snap_invested,
                    "actual_invested": actual_invested,
                    "diff": diff,
                })

    # 4. Broker reconciliation — compare with KIS account balance
    broker_balance = await kis_client.get_account_balance()
    if broker_balance:
        broker_positions = {p["stock_code"]: p for p in broker_balance["positions"]}

        async with pool.acquire() as conn:
            internal_positions = await conn.fetch(
                "SELECT stock_code, quantity, avg_price FROM portfolio_positions WHERE quantity > 0"
            )

        internal_map = {r["stock_code"]: r for r in internal_positions}

        # Position quantity mismatches
        all_codes = set(broker_positions.keys()) | set(internal_map.keys())
        for code in all_codes:
            broker_qty = broker_positions.get(code, {}).get("quantity", 0)
            internal_qty = internal_map.get(code, {}).get("quantity", 0) if code in internal_map else 0
            if broker_qty != internal_qty:
                mismatches.append({
                    "type": "position_qty_mismatch",
                    "stock_code": code,
                    "broker_qty": broker_qty,
                    "internal_qty": internal_qty,
                })

        # Cash mismatch vs broker
        if broker_balance["cash"] > 0:
            async with pool.acquire() as conn:
                snap = await conn.fetchrow("SELECT cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1")
            internal_cash = float(snap["cash"]) if snap else 0
            cash_diff = abs(broker_balance["cash"] - internal_cash)
            if cash_diff > 10000:  # 1만원 이상 차이
                mismatches.append({
                    "type": "broker_cash_mismatch",
                    "broker_cash": broker_balance["cash"],
                    "internal_cash": internal_cash,
                    "diff": cash_diff,
                })
    else:
        mismatches.append({"type": "broker_api_unavailable", "message": "KIS 잔고 조회 실패"})

    # Log reconciliation result
    await log_event(
        pool, source="reconciliation", event_type="eod_reconcile",
        payload={"mismatches": len(mismatches), "details": mismatches, "broker_queried": broker_balance is not None},
    )

    if mismatches:
        alert_msg = f"⚠️ [EOD 조정] {len(mismatches)}건 불일치 발견\n"
        for m in mismatches[:5]:
            alert_msg += f"  • {m['type']}: {m.get('stock_code', '')} {m.get('status', '')}\n"
        await notifier.alert(alert_msg)

    return {
        "status": "completed",
        "mismatches": len(mismatches),
        "details": mismatches,
    }
