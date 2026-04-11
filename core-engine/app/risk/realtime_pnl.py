"""Real-time portfolio P&L calculator.

Computes portfolio-level and per-position P&L using the latest prices
from Redis market state cache or DB fallback.
"""

import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.utils.market_calendar import KST

logger = logging.getLogger(__name__)


async def compute_realtime_pnl(
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
) -> dict:
    """Compute real-time portfolio P&L.

    Reads current positions, fetches latest prices from Redis cache
    (falling back to DB), and calculates unrealized P&L.

    Returns:
        {
            "total_value": float,
            "total_invested": float,
            "total_unrealized_pnl": float,
            "total_unrealized_pct": float,
            "cash": float,
            "daily_pnl": float,
            "daily_return_pct": float,
            "positions": [{stock_code, quantity, avg_price, current_price, unrealized_pnl, pnl_pct, weight}],
            "computed_at": str,
        }
    """
    now = datetime.now(KST)

    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """SELECT stock_code, quantity, avg_price, current_price
            FROM portfolio_positions WHERE quantity > 0"""
        )
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash, daily_pnl FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )

    cash = float(snapshot["cash"]) if snapshot else 0
    prev_total = float(snapshot["total_value"]) if snapshot else cash

    pos_details = []
    total_invested = 0
    total_current = 0

    for pos in positions:
        code = pos["stock_code"]
        qty = pos["quantity"]
        avg_price = float(pos["avg_price"])

        # Try Redis cache first (fastest)
        current_price = await _get_price_from_redis(redis, code)
        if current_price is None:
            current_price = float(pos["current_price"]) if pos["current_price"] else avg_price

        invested = qty * avg_price
        current_val = qty * current_price
        unrealized = current_val - invested
        pnl_pct = (unrealized / invested * 100) if invested > 0 else 0

        total_invested += invested
        total_current += current_val

        pos_details.append({
            "stock_code": code,
            "quantity": qty,
            "avg_price": round(avg_price, 0),
            "current_price": round(current_price, 0),
            "invested": round(invested, 0),
            "current_value": round(current_val, 0),
            "unrealized_pnl": round(unrealized, 0),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_value = cash + total_current
    total_unrealized = total_current - total_invested
    total_pct = (total_unrealized / total_invested * 100) if total_invested > 0 else 0

    # Daily P&L = current total - previous snapshot total
    daily_pnl = total_value - prev_total if prev_total > 0 else 0
    daily_return_pct = (daily_pnl / prev_total * 100) if prev_total > 0 else 0

    # Weight calculation
    for p in pos_details:
        p["weight"] = round(p["current_value"] / total_value * 100, 1) if total_value > 0 else 0

    # Sort by contribution (biggest P&L impact first)
    pos_details.sort(key=lambda x: abs(x["unrealized_pnl"]), reverse=True)

    return {
        "total_value": round(total_value, 0),
        "total_invested": round(total_invested, 0),
        "cash": round(cash, 0),
        "total_unrealized_pnl": round(total_unrealized, 0),
        "total_unrealized_pct": round(total_pct, 2),
        "daily_pnl": round(daily_pnl, 0),
        "daily_return_pct": round(daily_return_pct, 2),
        "positions_count": len(pos_details),
        "positions": pos_details,
        "computed_at": now.isoformat(),
    }


async def _get_price_from_redis(redis: aioredis.Redis, stock_code: str) -> float | None:
    """Get latest price from Redis market state cache."""
    try:
        import json
        raw = await redis.get(f"market:state:{stock_code}")
        if raw:
            data = json.loads(raw)
            price = data.get("price") or data.get("close")
            if price:
                return float(price)
    except Exception as e:
        logger.debug("Failed to get cached price for %s: %s", stock_code, e)
    return None
