"""KOSPI/KOSDAQ index historical data collector.

Fetches daily index data from Naver Finance for benchmark comparison.
Stores in ohlcv table with stock_code = 'KOSPI' or 'KOSDAQ'.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NAVER_INDEX_DAILY_URL = "https://finance.naver.com/sise/sise_index_day.naver"

# Naver code mapping
INDEX_CODES = {
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
}


async def fetch_index_history(index_name: str, pages: int = 20) -> list[dict]:
    """Fetch daily index data from Naver Finance.

    Args:
        index_name: "KOSPI" or "KOSDAQ"
        pages: number of pages to fetch (each page ~6 trading days)

    Returns: list of {time, close, open, high, low, volume}
    """
    code = INDEX_CODES.get(index_name)
    if not code:
        return []

    records = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            try:
                resp = await client.get(
                    NAVER_INDEX_DAILY_URL,
                    params={"code": code, "page": page},
                )
                soup = BeautifulSoup(resp.text, "lxml")
                rows = soup.select("table.type_1 tr")

                for row in rows:
                    cols = row.select("td")
                    if len(cols) < 6:
                        continue

                    date_text = cols[0].get_text(strip=True)
                    if not date_text or "." not in date_text:
                        continue

                    try:
                        dt = datetime.strptime(date_text, "%Y.%m.%d")
                        close = float(cols[1].get_text(strip=True).replace(",", ""))
                        change = cols[2].get_text(strip=True).replace(",", "")
                        volume = int(cols[5].get_text(strip=True).replace(",", "")) if cols[5].get_text(strip=True) else 0

                        # Naver doesn't show open/high/low for index — use close as proxy
                        records.append({
                            "time": dt.replace(tzinfo=timezone.utc),
                            "stock_code": index_name,
                            "close": Decimal(str(close)),
                            "open": Decimal(str(close)),
                            "high": Decimal(str(close)),
                            "low": Decimal(str(close)),
                            "volume": volume,
                            "value": 0,
                        })
                    except (ValueError, IndexError):
                        continue

            except Exception as e:
                logger.error("Index fetch failed for %s page %d: %s", index_name, page, e)

    # Deduplicate by date
    seen = set()
    unique = []
    for r in records:
        key = (r["stock_code"], r["time"].date())
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return sorted(unique, key=lambda x: x["time"])


async def collect_index_data(pool, index_name: str = "KOSPI", pages: int = 20) -> dict:
    """Fetch and store index historical data."""
    records = await fetch_index_history(index_name, pages)
    if not records:
        return {"status": "empty", "index": index_name, "inserted": 0}

    inserted = 0
    async with pool.acquire() as conn:
        for r in records:
            try:
                await conn.execute(
                    """INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '1d')
                    ON CONFLICT DO NOTHING""",
                    r["time"], r["stock_code"], r["open"], r["high"], r["low"],
                    r["close"], r["volume"], r["value"],
                )
                inserted += 1
            except Exception:
                pass

    return {"status": "ok", "index": index_name, "inserted": inserted, "total_fetched": len(records)}
