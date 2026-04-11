import json
import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
import pandas_ta as ta
import redis.asyncio as aioredis

from app.config import settings
from app.models.analysis import TechnicalIndicators, TechnicalResult, TechnicalSignal

logger = logging.getLogger(__name__)


async def _fetch_ohlcv_df(stock_code: str, interval: str, period: int, *, pool: asyncpg.Pool) -> pd.DataFrame:
    """Fetch OHLCV data from DB and return as DataFrame."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, high, low, close, volume, value
            FROM ohlcv
            WHERE stock_code = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
            """,
            stock_code,
            interval,
            period,
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [dict(r) for r in rows],
        columns=["time", "open", "high", "low", "close", "volume", "value"],
    )
    df = df.sort_values("time").reset_index(drop=True)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    return df


def _safe_float(val) -> float | None:
    """Convert numpy/pandas value to Python float, handling NaN."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else round(f, 4)
    except (TypeError, ValueError):
        return None


def _compute_indicators(df: pd.DataFrame) -> TechnicalIndicators:
    """Compute all technical indicators using pandas-ta."""
    if len(df) < 5:
        return TechnicalIndicators()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # --- Trend ---
    sma_5 = ta.sma(close, length=5)
    sma_20 = ta.sma(close, length=20)
    sma_60 = ta.sma(close, length=60)
    sma_120 = ta.sma(close, length=120)
    ema_12 = ta.ema(close, length=12)
    ema_26 = ta.ema(close, length=26)

    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    bb_df = ta.bbands(close, length=20, std=2)

    ichimoku_df = ta.ichimoku(high, low, close, tenkan=9, kijun=26, senkou=52)
    ich = ichimoku_df[0] if isinstance(ichimoku_df, tuple) and len(ichimoku_df) > 0 else None

    # --- Momentum ---
    rsi_14 = ta.rsi(close, length=14)
    stoch_df = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    cci_20 = ta.cci(high, low, close, length=20)
    willr_14 = ta.willr(high, low, close, length=14)
    roc_12 = ta.roc(close, length=12)

    # --- Volume ---
    obv = ta.obv(close, volume)
    mfi_14 = ta.mfi(high, low, close, volume, length=14)
    vwap = ta.vwap(high, low, close, volume)

    # --- Volatility ---
    atr_14 = ta.atr(high, low, close, length=14)
    kc_df = ta.kc(high, low, close, length=20, scalar=1.5)

    # Extract latest values
    last = len(df) - 1
    return TechnicalIndicators(
        # Trend
        sma_5=_safe_float(sma_5.iloc[last]) if sma_5 is not None else None,
        sma_20=_safe_float(sma_20.iloc[last]) if sma_20 is not None else None,
        sma_60=_safe_float(sma_60.iloc[last]) if sma_60 is not None and len(sma_60) > last else None,
        sma_120=_safe_float(sma_120.iloc[last]) if sma_120 is not None and len(sma_120) > last else None,
        ema_12=_safe_float(ema_12.iloc[last]) if ema_12 is not None else None,
        ema_26=_safe_float(ema_26.iloc[last]) if ema_26 is not None else None,
        macd=_safe_float(macd_df.iloc[last, 0]) if macd_df is not None and len(macd_df) > last else None,
        macd_signal=_safe_float(macd_df.iloc[last, 1]) if macd_df is not None and len(macd_df) > last else None,
        macd_hist=_safe_float(macd_df.iloc[last, 2]) if macd_df is not None and len(macd_df) > last else None,
        # pandas-ta returns Bollinger columns in BBL, BBM, BBU order.
        bb_upper=_safe_float(bb_df.iloc[last, 2]) if bb_df is not None and len(bb_df) > last else None,
        bb_middle=_safe_float(bb_df.iloc[last, 1]) if bb_df is not None and len(bb_df) > last else None,
        bb_lower=_safe_float(bb_df.iloc[last, 0]) if bb_df is not None and len(bb_df) > last else None,
        ichimoku_tenkan=_safe_float(ich.iloc[last, 0]) if ich is not None and len(ich) > last else None,
        ichimoku_kijun=_safe_float(ich.iloc[last, 1]) if ich is not None and len(ich) > last else None,
        # Momentum
        rsi_14=_safe_float(rsi_14.iloc[last]) if rsi_14 is not None else None,
        stoch_k=_safe_float(stoch_df.iloc[last, 0]) if stoch_df is not None and len(stoch_df) > last else None,
        stoch_d=_safe_float(stoch_df.iloc[last, 1]) if stoch_df is not None and len(stoch_df) > last else None,
        cci_20=_safe_float(cci_20.iloc[last]) if cci_20 is not None else None,
        willr_14=_safe_float(willr_14.iloc[last]) if willr_14 is not None else None,
        roc_12=_safe_float(roc_12.iloc[last]) if roc_12 is not None else None,
        # Volume
        obv=_safe_float(obv.iloc[last]) if obv is not None else None,
        mfi_14=_safe_float(mfi_14.iloc[last]) if mfi_14 is not None else None,
        vwap=_safe_float(vwap.iloc[last]) if vwap is not None else None,
        # Volatility
        atr_14=_safe_float(atr_14.iloc[last]) if atr_14 is not None else None,
        kc_upper=_safe_float(kc_df.iloc[last, 0]) if kc_df is not None and len(kc_df) > last else None,
        kc_lower=_safe_float(kc_df.iloc[last, 2]) if kc_df is not None and len(kc_df) > last and kc_df.shape[1] > 2 else None,
    )


def _generate_signals(indicators: TechnicalIndicators, current_price: float | None) -> list[TechnicalSignal]:
    """Generate trading signals from computed indicators."""
    signals = []
    price = current_price or 0

    # RSI signal
    if indicators.rsi_14 is not None:
        if indicators.rsi_14 < 30:
            signals.append(TechnicalSignal(indicator="RSI", signal="bullish", strength=0.8, description=f"RSI 과매도 ({indicators.rsi_14:.1f})"))
        elif indicators.rsi_14 > 70:
            signals.append(TechnicalSignal(indicator="RSI", signal="bearish", strength=0.8, description=f"RSI 과매수 ({indicators.rsi_14:.1f})"))
        else:
            signals.append(TechnicalSignal(indicator="RSI", signal="neutral", strength=0.3, description=f"RSI 중립 ({indicators.rsi_14:.1f})"))

    # MACD signal
    if indicators.macd_hist is not None:
        if indicators.macd_hist > 0:
            signals.append(TechnicalSignal(indicator="MACD", signal="bullish", strength=min(abs(indicators.macd_hist) / 100, 1.0), description="MACD 히스토그램 양전환"))
        else:
            signals.append(TechnicalSignal(indicator="MACD", signal="bearish", strength=min(abs(indicators.macd_hist) / 100, 1.0), description="MACD 히스토그램 음전환"))

    # Bollinger Bands
    if indicators.bb_upper and indicators.bb_lower and price > 0:
        if price >= indicators.bb_upper:
            signals.append(TechnicalSignal(indicator="BB", signal="bearish", strength=0.7, description="볼린저밴드 상단 돌파 (과매수)"))
        elif price <= indicators.bb_lower:
            signals.append(TechnicalSignal(indicator="BB", signal="bullish", strength=0.7, description="볼린저밴드 하단 돌파 (과매도)"))

    # SMA trend (price vs 20/60 SMA)
    if indicators.sma_20 and price > 0:
        if price > indicators.sma_20:
            signals.append(TechnicalSignal(indicator="SMA20", signal="bullish", strength=0.5, description="가격 > 20일 이동평균"))
        else:
            signals.append(TechnicalSignal(indicator="SMA20", signal="bearish", strength=0.5, description="가격 < 20일 이동평균"))

    if indicators.sma_60 and price > 0:
        if price > indicators.sma_60:
            signals.append(TechnicalSignal(indicator="SMA60", signal="bullish", strength=0.6, description="가격 > 60일 이동평균"))
        else:
            signals.append(TechnicalSignal(indicator="SMA60", signal="bearish", strength=0.6, description="가격 < 60일 이동평균"))

    # Golden/Death cross (SMA 20 vs 60)
    if indicators.sma_20 and indicators.sma_60:
        if indicators.sma_20 > indicators.sma_60:
            signals.append(TechnicalSignal(indicator="GoldenCross", signal="bullish", strength=0.7, description="골든크로스 (20일 > 60일)"))
        else:
            signals.append(TechnicalSignal(indicator="DeathCross", signal="bearish", strength=0.7, description="데드크로스 (20일 < 60일)"))

    # Stochastic
    if indicators.stoch_k is not None and indicators.stoch_d is not None:
        if indicators.stoch_k < 20 and indicators.stoch_d < 20:
            signals.append(TechnicalSignal(indicator="Stochastic", signal="bullish", strength=0.7, description="스토캐스틱 과매도"))
        elif indicators.stoch_k > 80 and indicators.stoch_d > 80:
            signals.append(TechnicalSignal(indicator="Stochastic", signal="bearish", strength=0.7, description="스토캐스틱 과매수"))

    # MFI
    if indicators.mfi_14 is not None:
        if indicators.mfi_14 < 20:
            signals.append(TechnicalSignal(indicator="MFI", signal="bullish", strength=0.6, description=f"MFI 과매도 ({indicators.mfi_14:.1f})"))
        elif indicators.mfi_14 > 80:
            signals.append(TechnicalSignal(indicator="MFI", signal="bearish", strength=0.6, description=f"MFI 과매수 ({indicators.mfi_14:.1f})"))

    return signals


def _compute_scores(signals: list[TechnicalSignal]) -> tuple[float, float, float]:
    """Compute trend, momentum, and overall scores from signals."""
    if not signals:
        return 0.0, 0.0, 0.0

    trend_indicators = {"SMA20", "SMA60", "GoldenCross", "DeathCross", "BB"}
    momentum_indicators = {"RSI", "MACD", "Stochastic", "MFI"}

    def avg_score(indicator_set: set) -> float:
        relevant = [s for s in signals if s.indicator in indicator_set]
        if not relevant:
            return 0.0
        total = sum(
            s.strength * (1.0 if s.signal == "bullish" else -1.0 if s.signal == "bearish" else 0.0)
            for s in relevant
        )
        return round(total / len(relevant), 4)

    trend = avg_score(trend_indicators)
    momentum = avg_score(momentum_indicators)
    overall = round((trend * 0.5 + momentum * 0.5), 4)

    return trend, momentum, overall


async def compute_technical(
    stock_code: str, interval: str = "1d", period: int = 200,
    *, pool: asyncpg.Pool, redis: aioredis.Redis,
) -> TechnicalResult:
    """Main entry point: compute all technical indicators for a stock."""
    now = datetime.now(timezone.utc)

    # Check Redis cache
    cache_key = f"analysis:technical:{stock_code}:{interval}"
    try:
        cached = await redis.get(cache_key)
        if cached:
            return TechnicalResult.model_validate_json(cached)
    except Exception as e:
        logger.debug("Redis cache read failed for %s: %s", cache_key, e)

    # Fetch data
    df = await _fetch_ohlcv_df(stock_code, interval, period, pool=pool)
    if df.empty:
        return TechnicalResult(
            stock_code=stock_code,
            interval=interval,
            indicators=TechnicalIndicators(),
            signals=[],
            computed_at=now,
        )

    current_price = _safe_float(df["close"].iloc[-1])

    # Compute
    indicators = _compute_indicators(df)
    signals = _generate_signals(indicators, current_price)
    trend_score, momentum_score, overall_score = _compute_scores(signals)

    result = TechnicalResult(
        stock_code=stock_code,
        interval=interval,
        current_price=current_price,
        indicators=indicators,
        signals=signals,
        trend_score=trend_score,
        momentum_score=momentum_score,
        overall_score=overall_score,
        computed_at=now,
    )

    # Cache result
    try:
        await redis.setex(cache_key, settings.cache_technical_ttl, result.model_dump_json())
    except Exception as e:
        logger.debug("Redis cache write failed for %s: %s", cache_key, e)

    return result
