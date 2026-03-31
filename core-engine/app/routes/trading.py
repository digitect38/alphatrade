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


TRADING_MODE_KEY = "trading:mode"  # Redis key for runtime mode


@router.get("/mode")
async def api_get_trading_mode(redis: aioredis.Redis = Depends(get_redis)):
    """Get current trading mode (paper/live)."""
    mode = await redis.get(TRADING_MODE_KEY)
    if mode:
        mode = mode.decode() if isinstance(mode, bytes) else mode
    else:
        mode = settings.kis_mode  # default from .env
    return {
        "mode": mode,
        "kis_base_url": settings.kis_base_url,
        "is_live": mode == "live",
    }


@router.post("/mode")
async def api_set_trading_mode(
    body: dict,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
    guard: TradingGuard = Depends(get_trading_guard),
    notifier: NotificationService = Depends(get_notifier),
):
    """Switch trading mode between paper and live.

    Body: {"mode": "paper"} or {"mode": "live", "confirm": true}

    Switching to live requires:
    1. confirm: true in request body
    2. Kill switch must be active (safety measure)
    3. Pre-launch checks must pass (no FAIL items)
    """
    from app.services.audit import log_event

    new_mode = body.get("mode", "paper")
    if new_mode not in ("paper", "live"):
        return {"error": f"Invalid mode: {new_mode}. Use 'paper' or 'live'."}

    current = await redis.get(TRADING_MODE_KEY)
    current_mode = (current.decode() if isinstance(current, bytes) else current) if current else settings.kis_mode

    if new_mode == current_mode:
        return {"status": "unchanged", "mode": current_mode}

    # Switching to live requires safety checks
    if new_mode == "live":
        if not body.get("confirm"):
            return {"error": "실전 전환은 confirm: true 필수", "hint": '{"mode": "live", "confirm": true}'}

        # Kill switch must be active during switch (prevents orders during transition)
        ks_active = await guard.is_kill_switch_active()
        if not ks_active:
            return {"error": "실전 전환 전 킬 스위치를 먼저 활성화하세요",
                    "hint": "POST /trading/kill-switch/activate"}

        await notifier.alert("🔴🔴🔴 <b>[실전 모드 전환]</b>\n모의투자 → 실전 매매로 전환되었습니다.\n킬 스위치 해제 후 실제 주문이 발생합니다.")

    elif new_mode == "paper":
        # Always allow switching back to paper
        await notifier.alert("🟢 <b>[모의 모드 전환]</b>\n실전 → 모의투자로 전환되었습니다.")

    await redis.set(TRADING_MODE_KEY, new_mode)

    await log_event(
        pool, source="trading_mode", event_type="mode_changed",
        payload={"from": current_mode, "to": new_mode, "operator": "dashboard"},
    )

    logger.warning("Trading mode changed: %s → %s", current_mode, new_mode)

    return {"status": "changed", "mode": new_mode, "previous": current_mode}


@router.get("/pre-launch-check")
async def api_pre_launch_check(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
    guard: TradingGuard = Depends(get_trading_guard),
):
    """Pre-launch readiness checklist for live trading.

    Validates all systems before allowing real-money trading.
    All checks run in parallel for fast response.
    """
    import asyncio

    # Run all checks in parallel
    async def _check_kis():
        try:
            balance = await kis_client.get_account_balance()
            return {"name": "KIS API 연결", "status": "PASS" if balance else "FAIL",
                    "detail": f"잔고 조회 {'성공' if balance else '실패'}"}
        except Exception as e:
            return {"name": "KIS API 연결", "status": "FAIL", "detail": str(e)}

    async def _check_kill_switch():
        ks_active = await guard.is_kill_switch_active()
        return {"name": "킬 스위치 해제", "status": "PASS" if not ks_active else "FAIL",
                "detail": "활성" if ks_active else "비활성"}

    async def _check_db():
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"name": "데이터베이스", "status": "PASS", "detail": "연결 정상"}
        except Exception as e:
            return {"name": "데이터베이스", "status": "FAIL", "detail": str(e)}

    async def _check_redis():
        try:
            await redis.ping()
            return {"name": "Redis", "status": "PASS", "detail": "연결 정상"}
        except Exception as e:
            return {"name": "Redis", "status": "FAIL", "detail": str(e)}

    async def _check_data():
        async with pool.acquire() as conn:
            recent = await conn.fetchval("SELECT COUNT(*) FROM ohlcv WHERE time > NOW() - INTERVAL '3 days'")
        return {"name": "최근 시세 데이터", "status": "PASS" if recent > 0 else "WARN",
                "detail": f"{recent}건 (최근 3일)"}

    async def _check_db_counts():
        async with pool.acquire() as conn:
            pos_count = await conn.fetchval("SELECT COUNT(*) FROM portfolio_positions WHERE quantity > 0")
            recon_count = await conn.fetchval(
                "SELECT COUNT(*) FROM audit_log WHERE source = 'reconciliation' AND event_time > NOW() - INTERVAL '14 days'"
            )
        return pos_count, recon_count

    results = await asyncio.gather(
        _check_kis(), _check_kill_switch(), _check_db(), _check_redis(),
        _check_data(), _check_db_counts(),
    )

    checks = list(results[:5])  # first 5 are dicts
    pos_count, recon_count = results[5]

    # 6. Trading mode
    is_live = settings.kis_mode == "live"
    checks.append({"name": "매매 모드", "status": "INFO",
                    "detail": f"{'실전' if is_live else '모의투자'} (KIS_MODE={settings.kis_mode})"})

    # 7. Positions
    checks.append({"name": "보유 포지션", "status": "INFO", "detail": f"{pos_count}종목"})

    # 8. EOD reconciliation history
    checks.append({"name": "EOD 정합성 이력 (14일)", "status": "PASS" if recon_count >= 10 else "WARN",
                    "detail": f"{recon_count}회 실행"})

    # 9. Backup exists
    import os
    backup_dir = os.environ.get("BACKUP_DIR", "/Users/woosj/DevelopMac/alpha_trade/data/backups")
    backup_exists = os.path.isdir(backup_dir) and bool(os.listdir(backup_dir)) if os.path.isdir(backup_dir) else False
    checks.append({"name": "백업 존재", "status": "PASS" if backup_exists else "WARN",
                    "detail": backup_dir})

    # Overall
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    overall = "READY" if fail_count == 0 and warn_count == 0 else ("NOT_READY" if fail_count > 0 else "CAUTION")

    return {
        "overall": overall,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "checks": checks,
        "kis_mode": settings.kis_mode,
    }


@router.post("/check-fills")
async def api_check_fills(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
):
    """Check in-flight orders for fill status updates.

    Polls broker for SUBMITTED/ACKED orders and updates their status.
    Should be called every 10-30 seconds during trading hours.
    """
    from app.execution.fill_monitor import check_inflight_orders
    return await check_inflight_orders(pool=pool, redis=redis, kis_client=kis_client)


@router.post("/cleanup-orders")
async def api_cleanup_orders(pool: asyncpg.Pool = Depends(get_db)):
    """End-of-day order cleanup — expire unresolved orders.

    Should be called after market close (15:40 KST).
    """
    from app.execution.order_cleanup import cleanup_eod_orders
    return await cleanup_eod_orders(pool=pool)


@router.get("/order-summary")
async def api_order_summary(pool: asyncpg.Pool = Depends(get_db)):
    """Daily order execution summary with fill rate and slippage stats."""
    from app.execution.order_cleanup import get_daily_order_summary
    return await get_daily_order_summary(pool=pool)


@router.get("/execution-quality")
async def api_execution_quality(
    days: int = 30,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Execution quality statistics — slippage and fill delay analysis."""
    from app.execution.fill_monitor import get_execution_quality_stats
    return await get_execution_quality_stats(pool=pool, days=days)


@router.post("/reconcile")
async def api_eod_reconcile(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
    notifier: NotificationService = Depends(get_notifier),
):
    """End-of-day broker reconciliation (v1.31 A-3, v1.4 enhanced).

    Full EOD sequence:
    1. Check & update in-flight order fills
    2. Clean up remaining unresolved orders
    3. Compare internal positions/cash/orders with BROKER ledger via KIS API

    Should be called daily after market close (via n8n WF or manually).
    """
    from app.services.audit import log_event
    from app.execution.fill_monitor import check_inflight_orders
    from app.execution.order_cleanup import cleanup_eod_orders

    # Step 0: Final fill check + cleanup before reconciliation
    fill_result = {}
    cleanup_result = {}
    try:
        fill_result = await check_inflight_orders(pool=pool, redis=redis, kis_client=kis_client)
        cleanup_result = await cleanup_eod_orders(pool=pool)
    except Exception as e:
        logger.warning("Pre-reconcile steps failed (non-fatal): %s", e)
        fill_result = {"error": str(e)}
        cleanup_result = {"error": str(e)}

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
        "pre_reconcile": {
            "fill_check": fill_result,
            "order_cleanup": cleanup_result,
        },
    }
