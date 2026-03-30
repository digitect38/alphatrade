"""Live market state cache (Redis-backed).

Continuously updated by KIS WebSocket ticks.
API reads from cache — zero remote fetch on request.

Redis keys:
  market:state:{stock_code} → Hash {price, change_pct, volume, ...}
  market:movers → Sorted Set by |change_pct|
  market:meta:updated_at → last global update timestamp
"""

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

STATE_PREFIX = "market:state:"
MOVERS_KEY = "market:movers"
META_KEY = "market:meta:updated_at"
STATE_TTL = 300  # 5 min TTL per stock (auto-expire stale)


class MarketStateCache:
    """Fast in-memory market state backed by Redis Hashes."""

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def update_tick(self, tick: dict):
        """Update state from a real-time tick."""
        code = tick.get("stock_code")
        if not code:
            return

        state = {
            "price": str(tick.get("price", 0)),
            "change_pct": str(tick.get("change_pct", 0)),
            "change": str(tick.get("change", 0)),
            "open": str(tick.get("open", 0)),
            "high": str(tick.get("high", 0)),
            "low": str(tick.get("low", 0)),
            "volume": str(tick.get("volume", 0)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        key = f"{STATE_PREFIX}{code}"
        await self.redis.hset(key, mapping=state)
        await self.redis.expire(key, STATE_TTL)

        # Update movers sorted set by |change_pct|
        abs_change = abs(float(tick.get("change_pct", 0)))
        await self.redis.zadd(MOVERS_KEY, {code: abs_change})

        # Update global timestamp
        await self.redis.set(META_KEY, state["updated_at"])

    async def update_from_db(self, pool, stock_code: str):
        """Seed cache from DB for stocks without live ticks."""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT close as price, volume,
                          close - LAG(close) OVER (ORDER BY time) as change
                   FROM ohlcv WHERE stock_code = $1 AND interval = '1d'
                   ORDER BY time DESC LIMIT 2""",
                stock_code,
            )
        if row and row["price"]:
            price = float(row["price"])
            change = float(row["change"]) if row["change"] else 0
            prev = price - change if change else price
            change_pct = (change / prev * 100) if prev > 0 else 0
            await self.update_tick({
                "stock_code": stock_code,
                "price": price,
                "change_pct": round(change_pct, 2),
                "change": round(change, 0),
                "volume": row["volume"] or 0,
            })

    async def get_stock_state(self, stock_code: str) -> dict | None:
        """Get cached state for a single stock."""
        data = await self.redis.hgetall(f"{STATE_PREFIX}{stock_code}")
        if not data:
            return None
        return {k: v for k, v in data.items()}

    async def get_all_states(self, stock_codes: list[str] | None = None) -> list[dict]:
        """Get cached states for multiple stocks."""
        if stock_codes:
            codes = stock_codes
        else:
            # Get all from movers set
            codes = await self.redis.zrevrange(MOVERS_KEY, 0, -1)

        results = []
        pipe = self.redis.pipeline()
        for code in codes:
            pipe.hgetall(f"{STATE_PREFIX}{code}")
        states = await pipe.execute()

        for code, state in zip(codes, states):
            if state:
                state["stock_code"] = code
                results.append(state)
        return results

    async def get_top_movers(self, limit: int = 20) -> list[dict]:
        """Get top movers by absolute change percentage."""
        codes = await self.redis.zrevrange(MOVERS_KEY, 0, limit - 1, withscores=True)
        results = []
        for code, score in codes:
            state = await self.redis.hgetall(f"{STATE_PREFIX}{code}")
            if state:
                state["stock_code"] = code
                state["abs_change_pct"] = score
                results.append(state)
        return results

    async def get_updated_at(self) -> str | None:
        return await self.redis.get(META_KEY)
