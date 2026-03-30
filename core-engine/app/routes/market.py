import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends

from fastapi import Query

import redis.asyncio as aioredis

from app.deps import get_db, get_redis, get_kis_client
from app.services.kis_api import KISClient
from app.services.market_state import MarketStateCache

logger = logging.getLogger(__name__)
router = APIRouter()


async def _fetch_stock_price(kis_client: KISClient, pool: asyncpg.Pool, row: dict) -> dict:
    """Fetch real-time price for a single stock, with DB fallback."""
    code = row["stock_code"]
    base = {"stock_code": code, "stock_name": row["stock_name"], "sector": row["sector"]}

    try:
        current = await kis_client.get_current_price(code)

        async with pool.acquire() as conn:
            prev = await conn.fetchrow(
                "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
                code,
            )
        prev_close = float(prev["close"]) if prev else 0

        if current:
            price = float(current.close)
            change = price - prev_close if prev_close > 0 else 0
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0
            return {
                **base, "price": price, "open": float(current.open),
                "high": float(current.high), "low": float(current.low),
                "prev_close": prev_close, "change": round(change, 0),
                "change_pct": round(change_pct, 2), "volume": current.volume,
            }
        else:
            return {**base, "price": prev_close, "change": 0, "change_pct": 0, "volume": 0, "stale": True}
    except Exception as e:
        logger.error("Price fetch failed for %s: %s", code, e)
        return {**base, "price": 0, "change": 0, "change_pct": 0, "volume": 0, "error": str(e)}


async def _attach_news_counts(pool: asyncpg.Pool, results: list[dict]):
    """Attach 7-day news counts to each stock result."""
    async with pool.acquire() as conn:
        news_counts = await conn.fetch(
            """
            SELECT unnest(stock_codes) as stock_code, count(*) as cnt
            FROM news WHERE time >= NOW() - INTERVAL '7 days'
            GROUP BY stock_code
            """
        )
    news_map = {r["stock_code"]: int(r["cnt"]) for r in news_counts}
    for item in results:
        item["news_count"] = news_map.get(item["stock_code"], 0)


@router.get("/prices")
async def api_market_prices(
    pool: asyncpg.Pool = Depends(get_db),
    kis_client: KISClient = Depends(get_kis_client),
):
    """Get real-time prices for all universe stocks."""
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        stocks = await conn.fetch(
            """
            SELECT s.stock_code, s.stock_name, s.sector
            FROM stocks s JOIN universe u ON s.stock_code = u.stock_code
            WHERE u.is_active = TRUE
            ORDER BY s.sector, s.stock_code
            """
        )

    results = [await _fetch_stock_price(kis_client, pool, row) for row in stocks]
    results.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    await _attach_news_counts(pool, results)

    return {"updated_at": now.isoformat(), "count": len(results), "stocks": results}


@router.get("/news/{stock_code}")
async def api_stock_news(stock_code: str, pool: asyncpg.Pool = Depends(get_db), limit: int = 20):
    """Get recent news articles for a stock."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, source, title, content, url
            FROM news WHERE $1 = ANY(stock_codes)
            ORDER BY time DESC LIMIT $2
            """,
            stock_code, limit,
        )

    if not rows:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT time, source, title, content, url FROM news ORDER BY time DESC LIMIT $1",
                limit,
            )

    return [
        {"time": r["time"].isoformat(), "source": r["source"], "title": r["title"],
         "content": (r["content"] or "")[:200], "url": r["url"]}
        for r in rows
    ]


@router.get("/search")
async def api_stock_search(
    q: str = Query(..., min_length=1, description="종목명 또는 종목코드 (부분 일치)"),
    pool: asyncpg.Pool = Depends(get_db),
    limit: int = Query(default=10, le=30),
):
    """Search stocks by name or code (fuzzy prefix match).

    Examples: '삼성' → 삼성전자, 삼성SDI, ... / 'SK' → SK하이닉스, SK텔레콤, ...
    """
    query = q.strip()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT stock_code, stock_name, market, sector
            FROM stocks
            WHERE stock_name ILIKE $1 OR stock_code LIKE $2
            ORDER BY
                CASE WHEN stock_name = $3 THEN 0
                     WHEN stock_name ILIKE $4 THEN 1
                     ELSE 2
                END,
                stock_name
            LIMIT $5
            """,
            f"%{query}%",       # $1: 이름 부분 일치
            f"{query}%",        # $2: 코드 prefix 일치
            query,              # $3: 정확 일치 우선
            f"{query}%",        # $4: prefix 일치 차선
            limit,
        )

    return [
        {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "market": r["market"],
            "sector": r["sector"],
            "label": f"{r['stock_name']} ({r['stock_code']})",
        }
        for r in rows
    ]


@router.get("/state")
async def api_market_state(
    redis: aioredis.Redis = Depends(get_redis),
    pool: asyncpg.Pool = Depends(get_db),
):
    """Get live market state from cache (zero remote fetch).

    Returns all stocks with cached prices, updated by WebSocket ticks.
    Falls back to DB seed if no live data.
    """
    cache = MarketStateCache(redis)
    states = await cache.get_all_states()

    # If cache empty, seed from universe
    if not states:
        async with pool.acquire() as conn:
            universe = await conn.fetch(
                "SELECT stock_code FROM universe WHERE is_active = TRUE"
            )
        for row in universe:
            await cache.update_from_db(pool, row["stock_code"])
        states = await cache.get_all_states()

    # Enrich with stock names from DB
    codes = [s["stock_code"] for s in states]
    if codes:
        async with pool.acquire() as conn:
            names = await conn.fetch(
                "SELECT stock_code, stock_name, sector FROM stocks WHERE stock_code = ANY($1::text[])",
                codes,
            )
        name_map = {r["stock_code"]: r for r in names}
        for s in states:
            info = name_map.get(s["stock_code"], {})
            s["stock_name"] = info.get("stock_name", "")
            s["sector"] = info.get("sector", "")

    updated_at = await cache.get_updated_at()
    return {
        "updated_at": updated_at,
        "count": len(states),
        "stocks": sorted(states, key=lambda x: abs(float(x.get("change_pct", 0))), reverse=True),
    }


@router.get("/movers")
async def api_market_movers(
    redis: aioredis.Redis = Depends(get_redis),
    pool: asyncpg.Pool = Depends(get_db),
    limit: int = Query(default=20, le=50),
):
    """Get top movers by absolute change percentage (from cache)."""
    cache = MarketStateCache(redis)
    movers = await cache.get_top_movers(limit)

    # Enrich with names
    codes = [m["stock_code"] for m in movers]
    if codes:
        async with pool.acquire() as conn:
            names = await conn.fetch(
                "SELECT stock_code, stock_name, sector FROM stocks WHERE stock_code = ANY($1::text[])",
                codes,
            )
        name_map = {r["stock_code"]: r for r in names}
        for m in movers:
            info = name_map.get(m["stock_code"], {})
            m["stock_name"] = info.get("stock_name", "")
            m["sector"] = info.get("sector", "")

    return {"count": len(movers), "movers": movers}
