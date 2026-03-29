import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.deps import get_db, get_redis, get_kis_client, get_naver_client, get_broker, get_risk_manager, get_notifier
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
