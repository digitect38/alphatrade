from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Request Models ---


class TechnicalRequest(BaseModel):
    stock_code: str
    interval: str = "1d"
    period: int = 200  # number of candles to analyze


class VolumeRequest(BaseModel):
    stock_code: str
    interval: str = "1d"


class SectorRequest(BaseModel):
    sector: str | None = None  # None = all sectors


class SummaryRequest(BaseModel):
    stock_code: str
    interval: str = "1d"


# --- Technical Indicators ---


class TechnicalIndicators(BaseModel):
    # Trend
    sma_5: float | None = None
    sma_20: float | None = None
    sma_60: float | None = None
    sma_120: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    ichimoku_tenkan: float | None = None
    ichimoku_kijun: float | None = None

    # Momentum
    rsi_14: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    cci_20: float | None = None
    willr_14: float | None = None
    roc_12: float | None = None

    # Volume-based
    obv: float | None = None
    mfi_14: float | None = None
    vwap: float | None = None

    # Volatility
    atr_14: float | None = None
    kc_upper: float | None = None
    kc_lower: float | None = None


class TechnicalSignal(BaseModel):
    indicator: str
    signal: Literal["bullish", "bearish", "neutral"]
    strength: float  # 0.0 ~ 1.0
    description: str


class TechnicalResult(BaseModel):
    stock_code: str
    interval: str
    current_price: float | None = None
    indicators: TechnicalIndicators
    signals: list[TechnicalSignal] = []
    trend_score: float = 0.0  # -1.0 (bearish) ~ 1.0 (bullish)
    momentum_score: float = 0.0
    overall_score: float = 0.0
    computed_at: datetime


# --- Volume Analysis ---


class VolumeResult(BaseModel):
    stock_code: str
    current_volume: int = 0
    avg_volume_20: float = 0.0
    volume_ratio: float = 0.0  # current / avg_20
    is_surge: bool = False  # > 2.0x
    price_volume_divergence: Literal["bullish", "bearish", "none"] = "none"
    volume_trend: Literal["increasing", "decreasing", "flat"] = "flat"
    obv_trend: Literal["increasing", "decreasing", "flat"] = "flat"
    computed_at: datetime


# --- Sector Analysis ---


class StockRank(BaseModel):
    stock_code: str
    stock_name: str
    return_1d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None


class SectorResult(BaseModel):
    sector: str
    return_1d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    relative_strength: float | None = None  # vs KOSPI
    top_stocks: list[StockRank] = []
    bottom_stocks: list[StockRank] = []
    computed_at: datetime


class SectorOverview(BaseModel):
    sectors: list[SectorResult] = []
    computed_at: datetime


# --- Summary ---


class AnalysisSummary(BaseModel):
    stock_code: str
    technical: TechnicalResult
    volume: VolumeResult
    overall_signal: Literal["strong_buy", "buy", "neutral", "sell", "strong_sell"]
    confidence: float  # 0.0 ~ 1.0
    computed_at: datetime
