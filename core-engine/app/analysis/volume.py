import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
import pandas_ta as ta

from app.config import settings
from app.models.analysis import VolumeResult

logger = logging.getLogger(__name__)


async def analyze_volume(stock_code: str, interval: str = "1d", *, pool: asyncpg.Pool) -> VolumeResult:
    """Analyze volume patterns for a stock."""
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, high, low, close, volume
            FROM ohlcv
            WHERE stock_code = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
            """,
            stock_code,
            interval,
            settings.analysis_volume_lookback,
        )

    if not rows:
        return VolumeResult(stock_code=stock_code, computed_at=now)

    df = pd.DataFrame([dict(r) for r in rows]).sort_values("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    if len(df) < 2:
        return VolumeResult(stock_code=stock_code, computed_at=now)

    current_vol = int(df["volume"].iloc[-1])

    # Volume ratio: current vs 20-day average
    vol_sma_20 = df["volume"].rolling(20).mean()
    avg_20 = float(vol_sma_20.iloc[-1]) if not np.isnan(vol_sma_20.iloc[-1]) else 1.0
    ratio = round(current_vol / avg_20, 4) if avg_20 > 0 else 0.0
    is_surge = ratio > settings.analysis_volume_surge_ratio

    # Price-volume divergence
    # Last 5 days: price up + volume down = bearish, price down + volume up = bullish
    divergence = "none"
    if len(df) >= 5:
        price_change = float(df["close"].iloc[-1]) - float(df["close"].iloc[-5])
        vol_change = float(df["volume"].iloc[-1:].mean()) - float(df["volume"].iloc[-5:-1].mean())

        if price_change > 0 and vol_change < 0:
            divergence = "bearish"
        elif price_change < 0 and vol_change > 0:
            divergence = "bullish"

    # Volume trend: 5-day SMA vs 20-day SMA
    vol_trend = "flat"
    vol_sma_5 = df["volume"].rolling(5).mean()
    if len(vol_sma_5) > 0 and len(vol_sma_20) > 0:
        sma5_val = float(vol_sma_5.iloc[-1]) if not np.isnan(vol_sma_5.iloc[-1]) else 0
        sma20_val = float(vol_sma_20.iloc[-1]) if not np.isnan(vol_sma_20.iloc[-1]) else 0
        if sma20_val > 0:
            vol_ratio = sma5_val / sma20_val
            if vol_ratio > 1.2:
                vol_trend = "increasing"
            elif vol_ratio < 0.8:
                vol_trend = "decreasing"

    # OBV trend
    obv_trend = "flat"
    obv = ta.obv(df["close"], df["volume"])
    if obv is not None and len(obv) >= 10:
        obv_sma_5 = obv.rolling(5).mean()
        obv_sma_10 = obv.rolling(10).mean()
        if not np.isnan(obv_sma_5.iloc[-1]) and not np.isnan(obv_sma_10.iloc[-1]):
            if obv_sma_5.iloc[-1] > obv_sma_10.iloc[-1]:
                obv_trend = "increasing"
            elif obv_sma_5.iloc[-1] < obv_sma_10.iloc[-1]:
                obv_trend = "decreasing"

    return VolumeResult(
        stock_code=stock_code,
        current_volume=current_vol,
        avg_volume_20=round(avg_20, 2),
        volume_ratio=ratio,
        is_surge=is_surge,
        price_volume_divergence=divergence,
        volume_trend=vol_trend,
        obv_trend=obv_trend,
        computed_at=now,
    )
