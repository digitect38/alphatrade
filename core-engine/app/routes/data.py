import logging
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.deps import get_db
from app.models.news import NewsRecord
from app.models.ohlcv import OHLCVRecord

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Sentiment ---


class SentimentInput(BaseModel):
    time: datetime
    stock_code: str
    source_type: str = "news"  # news, disclosure, social
    score: float  # -1.0 ~ 1.0
    confidence: float | None = None
    model: str = "claude"
    raw_text_id: str | None = None


@router.post("/sentiment")
async def store_sentiment(data: SentimentInput, pool: asyncpg.Pool = Depends(get_db)):
    """Store sentiment score from n8n AI Node."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sentiment_scores (time, stock_code, source_type, score, confidence, model, raw_text_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            data.time,
            data.stock_code,
            data.source_type,
            Decimal(str(data.score)),
            Decimal(str(data.confidence)) if data.confidence is not None else None,
            data.model,
            data.raw_text_id,
        )
    return {"status": "ok", "stock_code": data.stock_code, "score": data.score}


# --- News ---


@router.get("/news/unprocessed", response_model=list[NewsRecord])
async def get_unprocessed_news(
    pool: asyncpg.Pool = Depends(get_db),
    limit: int = Query(default=50, le=200),
):
    """Get news articles pending sentiment analysis."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, source, title, content, url, stock_codes, category
            FROM news
            WHERE is_processed = FALSE
            ORDER BY time DESC
            LIMIT $1
            """,
            limit,
        )
    return [
        NewsRecord(
            time=r["time"],
            source=r["source"],
            title=r["title"],
            content=r["content"],
            url=r["url"],
            stock_codes=r["stock_codes"] or [],
            category=r["category"],
        )
        for r in rows
    ]


@router.patch("/news/mark-processed")
async def mark_news_processed(urls: list[str], pool: asyncpg.Pool = Depends(get_db)):
    """Mark news articles as processed after sentiment analysis."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE news SET is_processed = TRUE WHERE url = ANY($1::text[])",
            urls,
        )
    return {"status": "ok", "updated": result}


# --- OHLCV ---


@router.get("/ohlcv/latest", response_model=list[OHLCVRecord])
async def get_latest_ohlcv(
    pool: asyncpg.Pool = Depends(get_db),
    stock_code: str = Query(...),
    interval: str = Query(default="1d"),
    limit: int = Query(default=30, le=500),
):
    """Get latest OHLCV records for a stock."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, stock_code, open, high, low, close, volume, value, interval
            FROM ohlcv
            WHERE stock_code = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
            """,
            stock_code,
            interval,
            limit,
        )
    return [
        OHLCVRecord(
            time=r["time"],
            stock_code=r["stock_code"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            value=r["value"],
            interval=r["interval"],
        )
        for r in rows
    ]
