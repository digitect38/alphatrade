import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.analysis.correlation import compute_correlation_matrix, granger_causality_test
from app.analysis.sector import analyze_sector
from app.analysis.sentiment import analyze_stock_sentiment, analyze_text_sentiment
from app.analysis.technical import compute_technical
from app.analysis.volume import analyze_volume
from app.deps import get_db, get_redis
from app.models.analysis import (
    AnalysisSummary,
    SectorOverview,
    SectorRequest,
    SummaryRequest,
    TechnicalRequest,
    TechnicalResult,
    VolumeRequest,
    VolumeResult,
)
from app.models.sentiment import (
    CausalityRequest,
    CausalityResult,
    CorrelationRequest,
    CorrelationResult,
    SentimentScore,
    StockSentimentRequest,
    StockSentimentResult,
    TextSentimentRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/technical", response_model=TechnicalResult)
async def api_analyze_technical(
    request: TechnicalRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Compute technical indicators for a stock."""
    return await compute_technical(
        stock_code=request.stock_code,
        interval=request.interval,
        period=request.period,
        pool=pool,
        redis=redis,
    )


@router.post("/volume", response_model=VolumeResult)
async def api_analyze_volume(
    request: VolumeRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Analyze volume patterns for a stock."""
    return await analyze_volume(
        stock_code=request.stock_code,
        interval=request.interval,
        pool=pool,
    )


@router.post("/sector", response_model=SectorOverview)
async def api_analyze_sector(
    request: SectorRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Analyze sector performance and relative strength."""
    return await analyze_sector(sector=request.sector, pool=pool)


@router.post("/summary", response_model=AnalysisSummary)
async def api_analyze_summary(
    request: SummaryRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Get combined technical + volume analysis summary."""
    now = datetime.now(timezone.utc)

    technical = await compute_technical(
        stock_code=request.stock_code,
        interval=request.interval,
        pool=pool,
        redis=redis,
    )
    volume = await analyze_volume(
        stock_code=request.stock_code,
        interval=request.interval,
        pool=pool,
    )

    # Determine overall signal
    score = technical.overall_score
    vol_boost = 0.0
    if volume.is_surge:
        vol_boost = 0.1 if score > 0 else -0.1
    combined = score + vol_boost

    if combined > 0.5:
        overall = "strong_buy"
    elif combined > 0.15:
        overall = "buy"
    elif combined < -0.5:
        overall = "strong_sell"
    elif combined < -0.15:
        overall = "sell"
    else:
        overall = "neutral"

    confidence = min(abs(combined), 1.0)

    return AnalysisSummary(
        stock_code=request.stock_code,
        technical=technical,
        volume=volume,
        overall_signal=overall,
        confidence=round(confidence, 4),
        computed_at=now,
    )


# --- Sentiment ---


@router.post("/sentiment", response_model=SentimentScore)
async def api_analyze_sentiment(request: TextSentimentRequest):
    """Analyze sentiment of financial text using LLM."""
    return await analyze_text_sentiment(text=request.text, model=request.model)


@router.post("/sentiment/stock", response_model=StockSentimentResult)
async def api_analyze_stock_sentiment(
    request: StockSentimentRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Get aggregated sentiment for a stock."""
    return await analyze_stock_sentiment(
        stock_code=request.stock_code,
        days=request.days,
        pool=pool,
    )


# --- Correlation & Causality ---


@router.post("/correlation", response_model=CorrelationResult)
async def api_analyze_correlation(
    request: CorrelationRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Compute correlation matrix between stocks."""
    return await compute_correlation_matrix(
        stock_codes=request.stock_codes,
        period=request.period,
        method=request.method,
        pool=pool,
    )


@router.post("/causality", response_model=CausalityResult)
async def api_analyze_causality(
    request: CausalityRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Perform Granger causality test between two stocks."""
    return await granger_causality_test(
        stock_a=request.stock_a,
        stock_b=request.stock_b,
        max_lag=request.max_lag,
        pool=pool,
    )
