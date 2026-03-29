"""Market index and sector trend API."""

import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


async def _fetch_sector_trend(conn, sector: str, stock_codes: list[str], days: int) -> dict | None:
    """Fetch trend data and stock details for a single sector."""
    daily_returns = await conn.fetch(
        """
        WITH daily AS (
            SELECT time::date as date, stock_code, close,
                   LAG(close) OVER (PARTITION BY stock_code ORDER BY time) as prev_close
            FROM ohlcv
            WHERE stock_code = ANY($1::text[]) AND interval = '1d'
            ORDER BY time DESC
        )
        SELECT date,
               AVG(CASE WHEN prev_close > 0 THEN (close - prev_close) / prev_close * 100 ELSE 0 END) as avg_return
        FROM daily
        WHERE prev_close IS NOT NULL
        GROUP BY date
        ORDER BY date DESC
        LIMIT $2
        """,
        stock_codes,
        days,
    )

    latest = await conn.fetch(
        """
        SELECT s.stock_code, s.stock_name,
               o.close as price,
               o.close - LAG(o.close) OVER (PARTITION BY o.stock_code ORDER BY o.time) as change
        FROM stocks s
        JOIN LATERAL (
            SELECT stock_code, close, time
            FROM ohlcv
            WHERE stock_code = s.stock_code AND interval = '1d'
            ORDER BY time DESC LIMIT 2
        ) o ON TRUE
        WHERE s.sector = $1 AND s.is_active = TRUE
        ORDER BY s.stock_code, o.time DESC
        """,
        sector,
    )

    trend_data = _build_trend_data(daily_returns)
    stock_details = _build_stock_details(latest)

    return {
        "sector": sector,
        "stock_count": len(stock_codes),
        "trend": trend_data,
        "cumulative_return": trend_data[-1]["cumulative"] if trend_data else 0,
        "stocks": stock_details,
    }


def _build_trend_data(daily_returns) -> list[dict]:
    """Build trend data with cumulative returns."""
    trend_data = [
        {"date": str(r["date"]), "return_pct": round(float(r["avg_return"]), 2)}
        for r in reversed(list(daily_returns))
    ]
    cumulative = 0.0
    for point in trend_data:
        cumulative += point["return_pct"]
        point["cumulative"] = round(cumulative, 2)
    return trend_data


def _build_stock_details(latest) -> list[dict]:
    """Deduplicate and build stock detail list."""
    details = []
    seen = set()
    for r in latest:
        code = r["stock_code"]
        if code in seen:
            continue
        seen.add(code)
        details.append({
            "stock_code": code,
            "stock_name": r["stock_name"],
            "price": float(r["price"]) if r["price"] else 0,
        })
    return details


@router.get("/sectors")
async def api_sector_trends(pool: asyncpg.Pool = Depends(get_db), days: int = Query(default=20, le=60)):
    """Get sector performance trends over time."""
    async with pool.acquire() as conn:
        sectors = await conn.fetch(
            "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL AND is_active = TRUE ORDER BY sector"
        )

        results = []
        for sec_row in sectors:
            sector = sec_row["sector"]
            stocks = await conn.fetch(
                "SELECT stock_code FROM stocks WHERE sector = $1 AND is_active = TRUE", sector,
            )
            stock_codes = [s["stock_code"] for s in stocks]
            if not stock_codes:
                continue

            result = await _fetch_sector_trend(conn, sector, stock_codes, days)
            if result:
                results.append(result)

    results.sort(key=lambda x: x["cumulative_return"], reverse=True)
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "sectors": results}


def _group_by_sector(rows) -> list[dict]:
    """Group stock rows by sector with averages."""
    sectors = {}
    for r in rows:
        sector = r["sector"] or "기타"
        if sector not in sectors:
            sectors[sector] = {"sector": sector, "stocks": [], "avg_change": 0}

        price = float(r["price"]) if r["price"] else 0
        change_pct = float(r["change_pct"]) if r["change_pct"] else 0

        sectors[sector]["stocks"].append({
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "price": price,
            "change_pct": round(change_pct, 2),
            "volume": r["volume"] or 0,
        })

    for sec in sectors.values():
        changes = [s["change_pct"] for s in sec["stocks"] if s["change_pct"] != 0]
        sec["avg_change"] = round(sum(changes) / len(changes), 2) if changes else 0
        sec["stock_count"] = len(sec["stocks"])

    return sorted(sectors.values(), key=lambda x: x["avg_change"], reverse=True)


@router.get("/overview")
async def api_market_overview(pool: asyncpg.Pool = Depends(get_db)):
    """Get overall market overview — all stocks grouped by sector with returns."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH latest AS (
                SELECT DISTINCT ON (stock_code)
                    stock_code, close as price, volume, time
                FROM ohlcv
                WHERE interval = '1d'
                ORDER BY stock_code, time DESC
            ),
            prev AS (
                SELECT DISTINCT ON (stock_code)
                    stock_code, close as prev_price
                FROM ohlcv
                WHERE interval = '1d'
                  AND time < (SELECT MAX(time) FROM ohlcv WHERE interval = '1d') - INTERVAL '1 hour'
                ORDER BY stock_code, time DESC
            )
            SELECT s.stock_code, s.stock_name, s.sector, s.market,
                   l.price, l.volume,
                   p.prev_price,
                   CASE WHEN p.prev_price > 0
                        THEN (l.price - p.prev_price) / p.prev_price * 100
                        ELSE 0 END as change_pct
            FROM stocks s
            LEFT JOIN latest l ON s.stock_code = l.stock_code
            LEFT JOIN prev p ON s.stock_code = p.stock_code
            WHERE s.is_active = TRUE
            ORDER BY s.sector, change_pct DESC NULLS LAST
            """
        )

    sector_list = _group_by_sector(rows)
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "sectors": sector_list}
