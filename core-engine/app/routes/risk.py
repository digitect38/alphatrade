import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.deps import get_db, get_redis

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/pnl")
async def api_realtime_pnl(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Real-time portfolio P&L with per-position breakdown.

    Uses Redis market state cache for latest prices, DB fallback.
    """
    from app.risk.realtime_pnl import compute_realtime_pnl
    return await compute_realtime_pnl(pool=pool, redis=redis)


@router.get("/var")
async def api_portfolio_var(
    lookback_days: int = 252,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Portfolio VaR/CVaR using historical simulation.

    Returns VaR at 95% and 99% confidence, CVaR (Expected Shortfall),
    marginal VaR per position, and portfolio risk metrics.

    Query params:
    - lookback_days: Historical window for return distribution (default 252)
    """
    from app.risk.var_calculator import compute_portfolio_var
    return await compute_portfolio_var(pool=pool, lookback_days=lookback_days)


@router.get("/stress-test")
async def api_stress_test(
    pool: asyncpg.Pool = Depends(get_db),
):
    """Run stress test scenarios on current portfolio.

    Applies historical crisis scenarios (COVID crash, rate hike, circuit breaker, etc.)
    and estimates portfolio impact.
    """
    from app.risk.stress_test import run_stress_test
    return await run_stress_test(pool=pool)


@router.get("/stress-test/{scenario}")
async def api_stress_test_single(
    scenario: str,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Run a single stress test scenario."""
    from app.risk.stress_test import run_stress_test
    return await run_stress_test(pool=pool, scenarios=[scenario])


@router.get("/alerts")
async def api_alert_stats(
    redis: aioredis.Redis = Depends(get_redis),
):
    """Get alert escalation statistics and active cooldowns."""
    from app.services.alert_escalation import AlertEscalation
    from app.services.notification import NotificationService
    escalation = AlertEscalation(NotificationService(), redis)
    return await escalation.get_alert_stats()
