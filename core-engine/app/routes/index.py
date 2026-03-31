"""Market index and sector trend API."""

import logging
from datetime import datetime, timezone

import asyncpg
import httpx
from fastapi import APIRouter, Depends, Query

from app.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

_NAVER_INDEX_URLS = {
    "KOSPI": "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:KOSPI",
    "KOSDAQ": "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:KOSDAQ",
}

_NAVER_FX_URL = "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW"


def _to_number(text: str) -> float:
    cleaned = (
        text.replace(",", "")
        .replace("%", "")
        .replace("+", "")
        .replace("\n", " ")
        .strip()
    )
    return float(cleaned) if cleaned else 0.0


def _parse_index_quote(payload: dict, name: str) -> dict:
    areas = payload.get("result", {}).get("areas", [])
    if not areas:
        raise ValueError(f"Missing index area for {name}")
    data = areas[0].get("datas", [])
    if not data:
        raise ValueError(f"Missing index data for {name}")
    item = data[0]

    return {
        "name": name,
        "price": float(item.get("nv", 0)) / 100,
        "change": float(item.get("cv", 0)) / 100,
        "change_pct": float(item.get("cr", 0)),
        "open": float(item.get("ov", 0)) / 100,
        "high": float(item.get("hv", 0)) / 100,
        "low": float(item.get("lv", 0)) / 100,
    }


async def _fetch_index_quote(name: str, url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AlphaTrade/1.0; +https://alphatrade.visualfactory.ai)",
        "Referer": "https://finance.naver.com/",
    }
    async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    return _parse_index_quote(response.json(), name)


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


@router.get("/realtime")
async def api_realtime_indexes():
    """Get live KOSPI/KOSDAQ quotes for dashboard index bar."""
    indexes = []
    for name, url in _NAVER_INDEX_URLS.items():
        try:
            quote = await _fetch_index_quote(name, url)
            quote["updated_at"] = datetime.now(timezone.utc).isoformat()
            indexes.append(quote)
        except Exception as exc:
            logger.error("Realtime index fetch failed for %s: %s", name, exc)
            indexes.append(
                {
                    "name": name,
                    "price": 0.0,
                    "change": 0.0,
                    "change_pct": 0.0,
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "updated_at": None,
                    "error": str(exc),
                }
            )

    # USD/KRW exchange rate
    try:
        fx = await _fetch_fx_rate()
        fx["updated_at"] = datetime.now(timezone.utc).isoformat()
        indexes.append(fx)
    except Exception as exc:
        logger.error("FX rate fetch failed: %s", exc)
        indexes.append({
            "name": "USD/KRW",
            "price": 0.0, "change": 0.0, "change_pct": 0.0,
            "open": 0.0, "high": 0.0, "low": 0.0,
            "updated_at": None, "error": str(exc),
        })

    return {"updated_at": datetime.now(timezone.utc).isoformat(), "indexes": indexes}


async def _fetch_fx_rate() -> dict:
    """Fetch USD/KRW exchange rate from Naver Finance mobile API."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }
    async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
        response = await client.get(_NAVER_FX_URL)
        response.raise_for_status()

    data = response.json()
    results = data.get("result", [])
    if not results:
        raise ValueError("No FX data returned")

    item = results[0]  # Most recent day
    price = _to_number(item.get("closePrice", "0"))
    change = _to_number(item.get("fluctuations", "0"))
    change_pct = _to_number(item.get("fluctuationsRatio", "0"))

    # Get previous day for open proxy (yesterday's close)
    prev_price = _to_number(results[1].get("closePrice", "0")) if len(results) > 1 else price

    return {
        "name": "USD/KRW",
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "open": prev_price,
        "high": price + max(change, 0),  # approximation
        "low": price + min(change, 0),   # approximation
    }
