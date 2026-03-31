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
from app.strategy.presets import list_presets, get_preset

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory active strategy config (persisted in Redis)
ACTIVE_STRATEGY_KEY = "strategy:active_config"


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


@router.get("/presets")
async def api_strategy_presets():
    """List all available strategy presets."""
    return {"presets": list_presets()}


@router.get("/active")
async def api_get_active_strategy(redis: aioredis.Redis = Depends(get_redis)):
    """Get currently active strategy configuration."""
    import json
    raw = await redis.get(ACTIVE_STRATEGY_KEY)
    if raw:
        return json.loads(raw)
    # Default: ensemble
    preset = get_preset("ensemble")
    return {"preset": "ensemble", **preset}


@router.post("/active")
async def api_set_active_strategy(
    body: dict,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Set active strategy configuration.

    Body options:
    1. {"preset": "momentum"} — use a preset
    2. {"preset": "custom", "weights": {...}, "buy_threshold": 0.2, "sell_threshold": -0.1}
    """
    import json
    preset_name = body.get("preset", "ensemble")
    preset = get_preset(preset_name)
    if not preset:
        return {"error": f"Unknown preset: {preset_name}"}

    config = {"preset": preset_name, **preset}

    # Override with custom values if provided
    if body.get("weights"):
        config["weights"] = body["weights"]
    if body.get("buy_threshold") is not None:
        config["buy_threshold"] = body["buy_threshold"]
    if body.get("sell_threshold") is not None:
        config["sell_threshold"] = body["sell_threshold"]

    await redis.set(ACTIVE_STRATEGY_KEY, json.dumps(config, ensure_ascii=False))
    logger.info("Active strategy changed to: %s", preset_name)
    return {"status": "ok", "active": config}
