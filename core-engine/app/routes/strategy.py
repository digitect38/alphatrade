import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.deps import get_db, get_redis
from app.models.strategy import (
    BacktestRequest,
    BacktestResult,
    BatchSignalRequest,
    BatchSignalResult,
    StrategySignalRequest,
    StrategySignalResult,
)
from app.strategy.backtest import run_backtest
from app.strategy.ensemble import generate_signal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/signal", response_model=StrategySignalResult)
async def api_strategy_signal(
    request: StrategySignalRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Generate ensemble trading signal for a stock."""
    return await generate_signal(
        stock_code=request.stock_code,
        interval=request.interval,
        pool=pool,
        redis=redis,
    )


@router.post("/signals/batch", response_model=BatchSignalResult)
async def api_batch_signals(
    request: BatchSignalRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Generate signals for multiple stocks or active universe."""
    now = datetime.now(timezone.utc)

    stock_codes = request.stock_codes
    if not stock_codes:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT stock_code FROM universe WHERE is_active = TRUE"
            )
            stock_codes = [r["stock_code"] for r in rows]

    signals = []
    for code in stock_codes:
        try:
            result = await generate_signal(code, request.interval, pool=pool, redis=redis)
            signals.append(result)
        except Exception as e:
            logger.error("Signal generation failed for %s: %s", code, e)

    buy_count = sum(1 for s in signals if s.signal == "BUY")
    sell_count = sum(1 for s in signals if s.signal == "SELL")
    hold_count = sum(1 for s in signals if s.signal == "HOLD")

    return BatchSignalResult(
        signals=signals,
        buy_count=buy_count,
        sell_count=sell_count,
        hold_count=hold_count,
        computed_at=now,
    )


@router.post("/backtest", response_model=BacktestResult)
async def api_backtest(
    request: BacktestRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Run backtest on historical data."""
    return await run_backtest(
        stock_code=request.stock_code,
        initial_capital=request.initial_capital,
        strategy=request.strategy,
        interval=request.interval,
        pool=pool,
    )
