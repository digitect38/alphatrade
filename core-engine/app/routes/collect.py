import io
import logging
from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.deps import get_db, get_redis, get_dart_client, get_kis_client, get_naver_client
from app.models.disclosure import DisclosureCollectionRequest, DisclosureCollectionResult
from app.models.news import NewsCollectionResult
from app.models.ohlcv import OHLCVCollectionRequest, OHLCVCollectionResult
from app.services.dart_api import DARTClient
from app.services.kis_api import KISClient
from app.services.naver_news import NaverNewsClient
from app.services.redis_publisher import RedisPublisher

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_intraday_snapshot(record):
    """Quote endpoint returns session OHLC, not true 1m OHLC. Store snapshot bars as last price."""
    if record.interval != "1m":
        return record
    record.open = record.close
    record.high = record.close
    record.low = record.close
    return record


async def _insert_news_records(conn, records, errors: list, sample: list) -> tuple[int, int]:
    """Insert news records, dedup by URL. Returns (inserted, duplicates)."""
    inserted = 0
    duplicates = 0
    for rec in records:
        try:
            if rec.url:
                exists = await conn.fetchval("SELECT 1 FROM news WHERE url = $1 LIMIT 1", rec.url)
                if exists:
                    duplicates += 1
                    continue
            await conn.execute(
                """INSERT INTO news (time, source, title, content, url, stock_codes, category, is_processed)
                VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE)""",
                rec.time, rec.source, rec.title, rec.content, rec.url, rec.stock_codes, rec.category,
            )
            inserted += 1
            if len(sample) < 3:
                sample.append(rec)
        except Exception as e:
            errors.append(f"Insert failed: {e}")
    return inserted, duplicates


async def _insert_disclosure_records(conn, records, errors: list, major_list: list) -> tuple[int, int]:
    """Insert disclosure records, dedup by rcept_no. Returns (inserted, duplicates)."""
    inserted = 0
    duplicates = 0
    for rec in records:
        try:
            exists = await conn.fetchval("SELECT 1 FROM disclosures WHERE rcept_no = $1 LIMIT 1", rec.rcept_no)
            if exists:
                duplicates += 1
                continue
            await conn.execute(
                """INSERT INTO disclosures (time, stock_code, report_name, report_type,
                    rcept_no, dcm_no, url, is_major, is_processed)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, FALSE)""",
                rec.time, rec.stock_code, rec.report_name, rec.report_type,
                rec.rcept_no, rec.dcm_no, rec.url, rec.is_major,
            )
            inserted += 1
            if rec.is_major:
                major_list.append(rec)
        except Exception as e:
            errors.append(f"Insert failed for {rec.rcept_no}: {e}")
    return inserted, duplicates


async def _collect_ohlcv_for_codes(
    stock_codes: list[str], interval: str, pool: asyncpg.Pool,
    kis_client: KISClient, publisher: RedisPublisher, errors: list,
) -> tuple[int, int]:
    """Fetch and store OHLCV data for each stock code. Returns (inserted, redis_published)."""
    inserted = 0
    redis_published = 0
    for code in stock_codes:
        try:
            record = await kis_client.get_current_price(code)
            if not record:
                errors.append(f"No data for {code}")
                continue
            record.interval = interval
            record = _normalize_intraday_snapshot(record)
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    record.time, record.stock_code, record.open, record.high,
                    record.low, record.close, record.volume, record.value, record.interval,
                )
                inserted += 1
            redis_published += await publisher.publish_ohlcv(code, record.model_dump(mode="json"))
        except Exception as e:
            errors.append(f"Failed for {code}: {e}")
    return inserted, redis_published


def _collection_status(errors: list, inserted: int) -> str:
    return "success" if not errors else ("partial" if inserted > 0 else "error")


@router.post("/news", response_model=NewsCollectionResult)
async def collect_news(
    pool: asyncpg.Pool = Depends(get_db),
    naver_client: NaverNewsClient = Depends(get_naver_client),
):
    """Collect news from Naver Finance and Google News RSS."""
    now = datetime.now(timezone.utc)
    errors = []
    sample = []
    inserted = duplicates = 0

    try:
        records = await naver_client.fetch_rss_news()
        async with pool.acquire() as conn:
            universe_rows = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE LIMIT 20")
        for row in universe_rows:
            records.extend(await naver_client.fetch_stock_news(row["stock_code"]))

        async with pool.acquire() as conn:
            inserted, duplicates = await _insert_news_records(conn, records, errors, sample)
    except Exception as e:
        errors.append(f"Collection failed: {e}")
        logger.error("News collection error: %s", e)

    # Callback to n8n for WF-03 sentiment analysis (v1.3 engine→n8n)
    if inserted > 0:
        from app.services.n8n_callback import on_news_collected
        await on_news_collected(inserted, [s.stock_codes[0] for s in sample if s.stock_codes])

    return NewsCollectionResult(
        status=_collection_status(errors, inserted),
        inserted=inserted, duplicates=duplicates, errors=errors,
        collected_at=now, sample=sample,
    )


@router.post("/disclosures", response_model=DisclosureCollectionResult)
async def collect_disclosures(
    pool: asyncpg.Pool = Depends(get_db),
    dart_client: DARTClient = Depends(get_dart_client),
    request: DisclosureCollectionRequest | None = None,
):
    """Collect disclosures from DART API."""
    now = datetime.now(timezone.utc)
    errors = []
    major_list = []
    inserted = duplicates = 0
    req = request or DisclosureCollectionRequest()

    try:
        records = await dart_client.get_disclosure_list(
            bgn_de=req.bgn_de, end_de=req.end_de,
            corp_code=req.corp_codes[0] if req.corp_codes else None,
        )
        async with pool.acquire() as conn:
            inserted, duplicates = await _insert_disclosure_records(conn, records, errors, major_list)
    except Exception as e:
        errors.append(f"Collection failed: {e}")
        logger.error("Disclosure collection error: %s", e)

    return DisclosureCollectionResult(
        status=_collection_status(errors, inserted),
        inserted=inserted, duplicates=duplicates, errors=errors,
        collected_at=now, major_disclosures=major_list,
    )


@router.post("/ohlcv", response_model=OHLCVCollectionResult)
async def collect_ohlcv(
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    kis_client: KISClient = Depends(get_kis_client),
    request: OHLCVCollectionRequest | None = None,
):
    """Collect OHLCV market data from 한국투자증권 API."""
    now = datetime.now(timezone.utc)
    errors = []
    inserted = duplicates = redis_published = 0
    req = request or OHLCVCollectionRequest()

    try:
        stock_codes = req.stock_codes
        if not stock_codes:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE")
                stock_codes = [r["stock_code"] for r in rows]

        if not stock_codes:
            return OHLCVCollectionResult(
                status="success", inserted=0,
                errors=["No stock codes to collect (universe is empty)"], collected_at=now,
            )

        publisher = RedisPublisher(redis)
        inserted, redis_published = await _collect_ohlcv_for_codes(
            stock_codes, req.interval, pool, kis_client, publisher, errors,
        )
    except Exception as e:
        errors.append(f"Collection failed: {e}")
        logger.error("OHLCV collection error: %s", e)

    return OHLCVCollectionResult(
        status=_collection_status(errors, inserted),
        inserted=inserted, duplicates=duplicates, errors=errors,
        collected_at=now, redis_published=redis_published,
    )


async def _fetch_krx_stocks(market_type: str, market_name: str) -> list[tuple[str, str, str, str | None]]:
    """Fetch stock list from KRX KIND for a given market."""
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params={"method": "download", "marketType": market_type}, headers=headers)

    # KRX returns EUC-KR HTML with a table
    import pandas as pd
    html = resp.content.decode("euc-kr", errors="replace")
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        return []

    df = tables[0]
    stocks = []
    for _, row in df.iterrows():
        raw_code = str(row["종목코드"]).strip()
        if not raw_code.isdigit():
            continue
        code = raw_code.zfill(6)
        name = str(row["회사명"]).strip()
        sector = str(row["업종"]).strip() if pd.notna(row.get("업종")) else None
        stocks.append((code, name, market_name, sector))
    return stocks


@router.post("/stocks")
async def collect_stocks(pool: asyncpg.Pool = Depends(get_db)):
    """Update all KOSPI + KOSDAQ stocks from KRX.

    Fetches the latest stock list from Korea Exchange and upserts into DB.
    Should be called daily before market open (e.g., 08:30 KST).
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    updated = 0
    errors = []

    try:
        all_stocks = []
        for mkt_type, mkt_name in [("stockMkt", "KOSPI"), ("kosdaqMkt", "KOSDAQ")]:
            stocks = await _fetch_krx_stocks(mkt_type, mkt_name)
            all_stocks.extend(stocks)
            logger.info("KRX %s: %d stocks fetched", mkt_name, len(stocks))

        async with pool.acquire() as conn:
            for code, name, market, sector in all_stocks:
                try:
                    result = await conn.execute(
                        """
                        INSERT INTO stocks (stock_code, stock_name, market, sector, is_active)
                        VALUES ($1, $2, $3, $4, TRUE)
                        ON CONFLICT (stock_code) DO UPDATE SET
                            stock_name = EXCLUDED.stock_name,
                            market = EXCLUDED.market,
                            sector = COALESCE(EXCLUDED.sector, stocks.sector),
                            is_active = TRUE,
                            updated_at = NOW()
                        """,
                        code, name, market, sector,
                    )
                    if "INSERT" in result:
                        inserted += 1
                    else:
                        updated += 1
                except Exception as e:
                    errors.append(f"{code}: {e}")

    except Exception as e:
        errors.append(f"KRX fetch failed: {e}")
        logger.error("Stock collection error: %s", e)

    return {
        "status": _collection_status(errors, inserted + updated),
        "collected_at": now.isoformat(),
        "inserted": inserted,
        "updated": updated,
        "total": inserted + updated,
        "errors": errors[:10],
    }


@router.post("/indexes")
async def collect_indexes(pool: asyncpg.Pool = Depends(get_db)):
    """Collect KOSPI + KOSDAQ daily index history from Naver Finance.

    Fetches ~100 trading days of index data for benchmark comparison.
    """
    from app.services.index_collector import collect_index_data

    results = []
    for index_name in ["KOSPI", "KOSDAQ"]:
        r = await collect_index_data(pool, index_name, pages=20)
        results.append(r)
        logger.info("Index %s: %d inserted", index_name, r.get("inserted", 0))

    return {"status": "ok", "results": results}
