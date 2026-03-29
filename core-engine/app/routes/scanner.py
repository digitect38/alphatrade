import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.deps import get_db, get_redis, get_kis_client, get_broker, get_risk_manager, get_notifier
from app.execution.broker import BrokerClient
from app.execution.risk_manager import RiskManager
from app.scanner.morning import run_morning_scan
from app.services.kis_api import KISClient
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/morning")
async def api_morning_scan(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
    broker: BrokerClient = Depends(get_broker),
    risk_mgr: RiskManager = Depends(get_risk_manager),
    notifier: NotificationService = Depends(get_notifier),
):
    """Run morning momentum scan (09:00~09:30).

    Scans all universe stocks for:
    - Gap up/down (전일 대비 2%+ 변동)
    - Volume surge (전일 대비 3배+ 거래량)

    Automatically buys top momentum stocks.
    """
    return await run_morning_scan(
        pool=pool, redis=redis, kis_client=kis_client,
        broker=broker, risk_mgr=risk_mgr, notifier=notifier,
    )


@router.get("/universe")
async def api_universe(pool: asyncpg.Pool = Depends(get_db)):
    """Get current trading universe."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.stock_code, s.stock_name, s.market, s.sector,
                   u.reason, u.added_at
            FROM stocks s
            JOIN universe u ON s.stock_code = u.stock_code
            WHERE u.is_active = TRUE
            ORDER BY s.sector, s.stock_code
            """
        )

    return [
        {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "market": r["market"],
            "sector": r["sector"],
        }
        for r in rows
    ]
