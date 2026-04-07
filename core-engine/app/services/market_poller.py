"""Two-tier market-state poller.

Tier 1: Top 100 stocks — every 1 minute (fast, priority)
Tier 2: All universe stocks — every 3 minutes (full coverage)

Both tiers use concurrent fetching with semaphore to respect KIS rate limits.
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

# Max concurrent KIS API calls (KIS limit: ~20/sec)
_CONCURRENCY = 10


async def _poll_single_stock(
    stock_code: str,
    kis_client: KISClient,
    pool: asyncpg.Pool,
    cache: MarketStateCache,
    sem: asyncio.Semaphore,
    save_1m: bool = True,
) -> bool:
    """Poll a single stock with semaphore-gated concurrency. Returns True on success."""
    async with sem:
        try:
            current = await kis_client.get_current_price(stock_code, pool=pool)
            if not current:
                return False

            async with pool.acquire() as conn:
                prev = await conn.fetchrow(
                    "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' "
                    "ORDER BY time DESC LIMIT 1",
                    stock_code,
                )

            prev_close = float(prev["close"]) if prev and prev["close"] else 0.0
            price = float(current.close)
            change = price - prev_close if prev_close > 0 else 0.0
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0.0

            await cache.update_tick({
                "stock_code": stock_code,
                "price": price,
                "change_pct": round(change_pct, 2),
                "change": round(change, 0),
                "open": float(current.open),
                "high": float(current.high),
                "low": float(current.low),
                "volume": current.volume,
                "prev_close": prev_close,
                "received_at": datetime.now(timezone.utc).isoformat(),
            })

            if save_1m and float(current.close) > 0:
                close_val = current.close
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                        current.time, stock_code, close_val, close_val,
                        close_val, close_val, current.volume, current.value, "1m",
                    )
            return True
        except Exception as exc:
            logger.debug("Poll failed for %s: %s", stock_code, exc)
            return False


async def refresh_market_state(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
    stock_codes: list[str] | None = None,
    save_1m: bool = True,
) -> dict[str, int]:
    """Refresh Redis market cache for given stocks (or full universe) using concurrent fetching."""
    cache = MarketStateCache(redis)

    if stock_codes is None:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE")
        stock_codes = [r["stock_code"] for r in rows]

    sem = asyncio.Semaphore(_CONCURRENCY)
    results = await asyncio.gather(*[
        _poll_single_stock(code, kis_client, pool, cache, sem, save_1m)
        for code in stock_codes
    ])

    updated = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    return {"updated": updated, "failed": failed, "count": len(stock_codes)}


# Backward compat alias
async def refresh_market_state_once(pool, redis, kis_client):
    return await refresh_market_state(pool, redis, kis_client)


async def market_state_fallback_loop(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
    interval_seconds: int = 60,
):
    """Two-tier polling loop.

    Tier 1: Top 100 stocks by trading value — every 1 minute
    Tier 2: Full universe — every 3 minutes
    """
    cycle = 0
    while True:
        try:
            session, _description = get_current_session()
            if session in _ACTIVE_SESSIONS:
                # Determine tier
                is_full_cycle = (cycle % 3 == 0)

                if is_full_cycle:
                    # Tier 2: all universe
                    result = await refresh_market_state(pool, redis, kis_client, save_1m=True)
                    logger.info(
                        "Tier 2 (full) refresh: updated=%d failed=%d total=%d",
                        result["updated"], result["failed"], result["count"],
                    )
                else:
                    # Tier 1: top 100 by recent trading value
                    async with pool.acquire() as conn:
                        top_rows = await conn.fetch("""
                            SELECT u.stock_code
                            FROM universe u
                            JOIN LATERAL (
                                SELECT SUM(volume) as total_vol
                                FROM ohlcv
                                WHERE stock_code = u.stock_code AND interval = '1d'
                                  AND time > NOW() - INTERVAL '7 days'
                            ) v ON TRUE
                            WHERE u.is_active = TRUE
                            ORDER BY v.total_vol DESC NULLS LAST
                            LIMIT 100
                        """)
                    top_codes = [r["stock_code"] for r in top_rows]
                    result = await refresh_market_state(pool, redis, kis_client, stock_codes=top_codes, save_1m=False)
                    logger.info(
                        "Tier 1 (top %d) refresh: updated=%d failed=%d",
                        len(top_codes), result["updated"], result["failed"],
                    )

                cycle += 1
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Market poll loop error: %s", exc)

        await asyncio.sleep(interval_seconds)
