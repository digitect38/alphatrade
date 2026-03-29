"""Shared fixtures for all tests."""

import os
# Disable rate limiting and auth during tests
os.environ.setdefault("RATE_LIMIT_MAX", "10000")
os.environ.setdefault("API_AUTH_KEY", "")

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from app.models.analysis import TechnicalIndicators, TechnicalResult, VolumeResult
from app.models.sentiment import StockSentimentResult, SentimentScore


# --- Sample Data Fixtures ---


@pytest.fixture
def sample_ohlcv_rows():
    """60 days of synthetic OHLCV data."""
    import random
    random.seed(42)
    base_price = 60000
    rows = []
    for i in range(60):
        p = base_price + random.randint(-3000, 3000)
        rows.append({
            "time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "stock_code": "005930",
            "open": Decimal(str(p - 500)),
            "high": Decimal(str(p + 1000)),
            "low": Decimal(str(p - 1500)),
            "close": Decimal(str(p)),
            "volume": random.randint(10_000_000, 30_000_000),
            "value": random.randint(500_000_000_000, 1_500_000_000_000),
            "interval": "1d",
        })
    return rows


@pytest.fixture
def sample_technical_result():
    return TechnicalResult(
        stock_code="005930",
        interval="1d",
        current_price=60000,
        indicators=TechnicalIndicators(
            sma_5=59500, sma_20=58000, sma_60=57000, sma_120=55000,
            ema_12=59000, ema_26=58500,
            macd=500, macd_signal=300, macd_hist=200,
            bb_upper=62000, bb_middle=59000, bb_lower=56000,
            rsi_14=55, stoch_k=60, stoch_d=55,
            cci_20=100, willr_14=-40, roc_12=3.5,
            obv=150000000, mfi_14=60, vwap=59500,
            atr_14=1500, kc_upper=61500, kc_lower=56500,
        ),
        signals=[],
        trend_score=0.3,
        momentum_score=0.2,
        overall_score=0.25,
        computed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_volume_result():
    return VolumeResult(
        stock_code="005930",
        current_volume=20000000,
        avg_volume_20=15000000,
        volume_ratio=1.33,
        is_surge=False,
        price_volume_divergence="none",
        volume_trend="flat",
        obv_trend="increasing",
        computed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_sentiment_result():
    return StockSentimentResult(
        stock_code="005930",
        overall_score=0.6,
        news_score=0.5,
        disclosure_score=0.7,
        article_count=5,
        recent_sentiments=[
            SentimentScore(score=0.6, confidence=0.8, reasoning="긍정적", model="claude"),
        ],
        computed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def bearish_technical_result():
    return TechnicalResult(
        stock_code="005930",
        interval="1d",
        current_price=50000,
        indicators=TechnicalIndicators(
            sma_5=52000, sma_20=55000, sma_60=58000, sma_120=60000,
            ema_12=53000, ema_26=55000,
            macd=-2000, macd_signal=-1500, macd_hist=-500,
            bb_upper=58000, bb_middle=55000, bb_lower=52000,
            rsi_14=25, stoch_k=15, stoch_d=18,
            cci_20=-150, willr_14=-85, roc_12=-8.0,
            obv=80000000, mfi_14=18, vwap=54000,
            atr_14=2500, kc_upper=59000, kc_lower=51000,
        ),
        signals=[],
        trend_score=-0.7,
        momentum_score=-0.6,
        overall_score=-0.65,
        computed_at=datetime.now(timezone.utc),
    )
