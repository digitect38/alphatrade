"""Fallback market-state poller.

When KIS real-time WebSocket ticks are missing or silent, this task keeps the
Redis-backed market cache fresh enough for the dashboard to remain dynamic.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.services.kis_api import KISClient
from app.services.market_state import MarketStateCache
from app.utils.market_calendar import MarketSession, get_current_session

logger = logging.getLogger(__name__)

_ACTIVE_SESSIONS = {
    MarketSession.PRE_MARKET,
    MarketSession.OPENING_AUCTION,
    MarketSession.REGULAR,
    MarketSession.CLOSING_AUCTION,
}


async def refresh_market_state_once(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
) -> dict[str, int]:
    """Refresh Redis market cache from polling current prices."""
    cache = MarketStateCache(redis)

    async with pool.acquire() as conn:
        universe = await conn.fetch(
            "SELECT stock_code FROM universe WHERE is_active = TRUE ORDER BY stock_code"
        )

    updated = 0
    failed = 0

    for row in universe:
        stock_code = row["stock_code"]
        try:
            current = await kis_client.get_current_price(stock_code)
            if not current:
                failed += 1
                continue

            async with pool.acquire() as conn:
                prev = await conn.fetchrow(
                    """
                    SELECT close
                    FROM ohlcv
                    WHERE stock_code = $1 AND interval = '1d'
                    ORDER BY time DESC
                    LIMIT 1
                    """,
                    stock_code,
                )

            prev_close = float(prev["close"]) if prev and prev["close"] else 0.0
            price = float(current.close)
            change = price - prev_close if prev_close > 0 else 0.0
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0.0

            await cache.update_tick(
                {
                    "stock_code": stock_code,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "change": round(change, 0),
                    "open": float(current.open),
                    "high": float(current.high),
                    "low": float(current.low),
                    "volume": current.volume,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Also save to DB as 1m tick for chart display (skip bad data)
            # Normalize: KIS returns session OHLC, not true 1m OHLC — store as close-only snapshot
            if float(current.close) > 0:
                close_val = current.close
                async with pool.acquire() as conn:
                    await conn.execute(
                    """INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    current.time, stock_code, close_val, close_val,
                    close_val, close_val, current.volume, current.value, "1m",
                )

            updated += 1
        except Exception as exc:
            failed += 1
            logger.debug("Market poll failed for %s: %s", stock_code, exc)

    return {"updated": updated, "failed": failed, "count": len(universe)}


async def market_state_fallback_loop(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
    interval_seconds: int = 30,
):
    """Continuously refresh market cache during active sessions."""
    while True:
        try:
            session, _description = get_current_session()
            if session in _ACTIVE_SESSIONS:
                result = await refresh_market_state_once(pool, redis, kis_client)
                logger.info(
                    "Market fallback refresh completed: updated=%d failed=%d total=%d",
                    result["updated"],
                    result["failed"],
                    result["count"],
                )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Market fallback loop error: %s", exc)

        await asyncio.sleep(interval_seconds)
