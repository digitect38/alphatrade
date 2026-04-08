"""Shared Redis cache utilities — stock price lookups etc."""

import redis.asyncio as aioredis


async def get_realtime_price(redis: aioredis.Redis, code: str) -> dict | None:
    """Get real-time price from Redis market state cache (updated by poller).

    Returns: {"price": float, "change_pct": float, "change": float, "volume": int, "updated_at": str}
    or None if not cached.
    """
    try:
        data = await redis.hgetall(f"market:state:{code}")
        if not data:
            return None

        def _v(key: str) -> float:
            val = data.get(key.encode()) or data.get(key)
            return float(val) if val else 0.0

        price = _v("price")
        if price <= 0:
            return None

        updated_raw = data.get(b"updated_at") or data.get("updated_at", b"")
        updated_at = updated_raw.decode() if isinstance(updated_raw, bytes) else str(updated_raw)

        return {
            "price": price,
            "change_pct": _v("change_pct"),
            "change": _v("change"),
            "volume": int(_v("volume")),
            "updated_at": updated_at,
        }
    except Exception:
        return None
