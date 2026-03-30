from datetime import datetime

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from app.analysis.technical import compute_technical
from app.analysis.volume import analyze_volume
from app.deps import get_db, get_redis
from app.services.market_state import MarketStateCache
from app.utils.market_calendar import KST, get_current_session

router = APIRouter()

RANGE_CONFIG: dict[str, tuple[str, int]] = {
    "1D": ("1m", 240),
    "5D": ("1m", 600),
    "1M": ("1d", 30),
    "3M": ("1d", 90),
    "6M": ("1d", 180),
    "YTD": ("1d", 260),
    "1Y": ("1d", 260),
}


async def _load_profile(pool: asyncpg.Pool, stock_code: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT stock_code, stock_name, market, sector
            FROM stocks
            WHERE stock_code = $1
            LIMIT 1
            """,
            stock_code,
        )


async def _load_market_state(redis: aioredis.Redis, pool: asyncpg.Pool, stock_code: str) -> dict:
    cache_state: dict | None = None
    try:
        cache = MarketStateCache(redis)
        cache_state = await cache.get_stock_state(stock_code)
    except Exception:
        cache_state = None

    if cache_state:
        return {
            "current_price": float(cache_state.get("price", 0) or 0),
            "change": float(cache_state.get("change", 0) or 0),
            "change_pct": float(cache_state.get("change_pct", 0) or 0),
            "volume": int(float(cache_state.get("volume", 0) or 0)),
            "updated_at": cache_state.get("updated_at"),
        }

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, close, volume
            FROM ohlcv
            WHERE stock_code = $1 AND interval = '1d'
            ORDER BY time DESC
            LIMIT 2
            """,
            stock_code,
        )

    latest = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None
    current_price = float(latest["close"]) if latest and latest["close"] else 0.0
    prev_close = float(prev["close"]) if prev and prev["close"] else current_price
    change = current_price - prev_close if prev_close else 0.0
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    return {
        "current_price": round(current_price, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": int(latest["volume"]) if latest and latest["volume"] else 0,
        "updated_at": latest["time"].isoformat() if latest else None,
    }


async def _load_chart(pool: asyncpg.Pool, stock_code: str, range_key: str):
    interval, limit = RANGE_CONFIG.get(range_key, RANGE_CONFIG["1M"])
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, high, low, close, volume
            FROM ohlcv
            WHERE stock_code = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
            """,
            stock_code,
            interval,
            limit,
        )

        if interval == "1m" and _is_synthetic_intraday(rows):
            fallback_limit = 5 if range_key == "1D" else 22
            rows = await conn.fetch(
                """
                SELECT time, open, high, low, close, volume
                FROM ohlcv
                WHERE stock_code = $1 AND interval = '1d'
                ORDER BY time DESC
                LIMIT $2
                """,
                stock_code,
                fallback_limit,
            )
            interval = "1d"

    points = [
        {
            "time": row["time"].isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        }
        for row in reversed(rows)
    ]
    return {"stock_code": stock_code, "range": range_key, "interval": interval, "points": points}


def _is_synthetic_intraday(rows) -> bool:
    if len(rows) < 10:
        return False

    unique_bars = {
        (
            float(row["open"] or 0),
            float(row["high"] or 0),
            float(row["low"] or 0),
            float(row["close"] or 0),
            int(row["volume"] or 0),
        )
        for row in rows
    }
    return len(unique_bars) <= 3


async def _load_daily_bars(pool: asyncpg.Pool, stock_code: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, close
            FROM ohlcv
            WHERE stock_code = $1 AND interval = '1d'
            ORDER BY time ASC
            LIMIT 260
            """,
            stock_code,
        )
    return [
        {"time": row["time"], "close": float(row["close"])}
        for row in rows
        if row["close"] is not None and row["time"] is not None
    ]


def _calc_return(closes: list[float], bars: int) -> float:
    if len(closes) < 2:
        return 0.0
    last = closes[-1]
    base_index = max(len(closes) - bars, 0)
    base = closes[base_index]
    if base <= 0:
        return 0.0
    return round((last / base - 1) * 100, 2)


def _calc_ytd_return(daily_bars: list[dict]) -> float:
    if len(daily_bars) < 2:
        return 0.0

    latest_time = daily_bars[-1]["time"]
    current_year = latest_time.astimezone(KST).year if hasattr(latest_time, "astimezone") else latest_time.year

    ytd_bars = []
    for bar in daily_bars:
        bar_time = bar["time"]
        bar_year = bar_time.astimezone(KST).year if hasattr(bar_time, "astimezone") else bar_time.year
        if bar_year == current_year:
            ytd_bars.append(bar)

    if len(ytd_bars) < 2:
        return 0.0

    base = ytd_bars[0]["close"]
    last = ytd_bars[-1]["close"]
    if base <= 0:
        return 0.0
    return round((last / base - 1) * 100, 2)


async def _load_recent_orders(pool: asyncpg.Pool, stock_code: str, limit: int = 8) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_id, time, stock_code, side, order_type, quantity,
                   price, filled_qty, filled_price, status, slippage, commission
            FROM orders
            WHERE stock_code = $1
            ORDER BY time DESC
            LIMIT $2
            """,
            stock_code,
            limit,
        )
    return [
        {
            "order_id": row["order_id"],
            "time": row["time"].isoformat(),
            "stock_code": row["stock_code"],
            "side": row["side"],
            "order_type": row["order_type"],
            "quantity": row["quantity"],
            "price": float(row["price"]) if row["price"] else None,
            "filled_qty": row["filled_qty"],
            "filled_price": float(row["filled_price"]) if row["filled_price"] else None,
            "status": row["status"],
            "slippage": float(row["slippage"]) if row["slippage"] else None,
            "commission": float(row["commission"]) if row["commission"] else None,
        }
        for row in rows
    ]


async def _load_recent_news(pool: asyncpg.Pool, stock_code: str, limit: int = 5) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, source, title, content, url
            FROM news
            WHERE $1 = ANY(stock_codes)
            ORDER BY time DESC
            LIMIT $2
            """,
            stock_code,
            limit,
        )
    return [
        {
            "time": row["time"].isoformat(),
            "source": row["source"],
            "title": row["title"],
            "content": (row["content"] or "")[:200],
            "url": row["url"],
        }
        for row in rows
    ]


async def _load_signal_summary(pool: asyncpg.Pool, redis: aioredis.Redis, stock_code: str) -> dict:
    technical = await compute_technical(stock_code=stock_code, interval="1d", pool=pool, redis=redis)
    volume = await analyze_volume(stock_code=stock_code, interval="1d", pool=pool)
    score = technical.overall_score + (0.1 if volume.is_surge and technical.overall_score > 0 else -0.1 if volume.is_surge else 0.0)

    if score > 0.5:
        overall_signal = "strong_buy"
    elif score > 0.15:
        overall_signal = "buy"
    elif score < -0.5:
        overall_signal = "strong_sell"
    elif score < -0.15:
        overall_signal = "sell"
    else:
        overall_signal = "neutral"

    return {
        "overall_signal": overall_signal,
        "confidence": round(min(abs(score), 1.0), 4),
        "trend_score": technical.trend_score,
        "momentum_score": technical.momentum_score,
        "overall_score": technical.overall_score,
        "top_signals": [
            {
                "indicator": signal.indicator,
                "signal": signal.signal,
                "strength": signal.strength,
                "description": signal.description,
            }
            for signal in technical.signals[:5]
        ],
    }


@router.get("/{stock_code}/overview")
async def api_asset_overview(
    stock_code: str,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    profile = await _load_profile(pool, stock_code)
    state = await _load_market_state(redis, pool, stock_code)
    now = datetime.now(KST)
    session, description = get_current_session(now)

    return {
        "stock_code": stock_code,
        "stock_name": profile["stock_name"] if profile else stock_code,
        "market": profile["market"] if profile else None,
        "sector": profile["sector"] if profile else None,
        **state,
        "session": {
            "current_session": session.value,
            "description": description,
            "kst_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


@router.get("/{stock_code}/chart")
async def api_asset_chart(
    stock_code: str,
    range_key: str = Query(default="1M", alias="range"),
    pool: asyncpg.Pool = Depends(get_db),
):
    return await _load_chart(pool, stock_code, range_key)


@router.get("/{stock_code}/period-returns")
async def api_asset_period_returns(
    stock_code: str,
    pool: asyncpg.Pool = Depends(get_db),
):
    daily_bars = await _load_daily_bars(pool, stock_code)
    closes = [bar["close"] for bar in daily_bars]
    return {
        "stock_code": stock_code,
        "returns": {
            "1D": _calc_return(closes, 2),
            "5D": _calc_return(closes, 6),
            "1M": _calc_return(closes, 22),
            "3M": _calc_return(closes, 66),
            "6M": _calc_return(closes, 132),
            "YTD": _calc_ytd_return(daily_bars),
            "1Y": _calc_return(closes, 252),
        },
    }


@router.get("/{stock_code}/execution-context")
async def api_asset_execution_context(
    stock_code: str,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    now = datetime.now(KST)
    session, description = get_current_session(now)
    orders = await _load_recent_orders(pool, stock_code)
    news = await _load_recent_news(pool, stock_code)
    signal_summary = await _load_signal_summary(pool, redis, stock_code)

    return {
        "stock_code": stock_code,
        "session": {
            "current_session": session.value,
            "description": description,
            "kst_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "latest_order": orders[0] if orders else None,
        "recent_orders": orders,
        "recent_news": news,
        "signal_summary": signal_summary,
    }
