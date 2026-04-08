"""Backtest signal generation — production-aligned 4-factor ensemble.

Replicates the scoring from signals.py + presets.py using vectorised indicators.
"""

import numpy as np
import pandas as pd
import pandas_ta as ta


def generate_backtest_signals(df: pd.DataFrame, strategy: str) -> tuple[pd.Series, pd.Series]:
    """Generate buy/sell signals using the production ensemble engine.

    Returns:
        signals: Series with 1 (buy), -1 (sell), 0 (hold).
        reasons: Series with top contributing factor name.
    """
    from app.strategy.presets import STRATEGY_PRESETS

    preset = STRATEGY_PRESETS.get(strategy, STRATEGY_PRESETS["ensemble"])
    weights = preset["weights"]
    buy_threshold = preset["buy_threshold"]
    sell_threshold = preset["sell_threshold"]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    n = len(df)

    # Pre-compute all technical indicators
    sma_20 = ta.sma(close, length=20)
    sma_60 = ta.sma(close, length=60) if n >= 60 else pd.Series(np.nan, index=df.index)
    rsi = ta.rsi(close, length=14)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_hist = macd_df.iloc[:, 1] if macd_df is not None and len(macd_df.columns) >= 2 else pd.Series(np.nan, index=df.index)
    roc_12 = ta.roc(close, length=12) if n >= 13 else pd.Series(np.nan, index=df.index)

    bb = ta.bbands(close, length=20, std=2)
    bb_lower = bb.iloc[:, 2] if bb is not None else pd.Series(np.nan, index=df.index)
    bb_upper = bb.iloc[:, 0] if bb is not None else pd.Series(np.nan, index=df.index)

    stoch = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    stoch_k = stoch.iloc[:, 0] if stoch is not None else pd.Series(np.nan, index=df.index)

    willr = ta.willr(high, low, close, length=14)
    if willr is None:
        willr = pd.Series(np.nan, index=df.index)

    vol_sma5 = ta.sma(volume.astype(float), length=5)
    vol_sma20 = ta.sma(volume.astype(float), length=20)
    obv = ta.obv(close, volume)
    obv_sma5 = ta.sma(obv, length=5) if obv is not None else None
    obv_sma10 = ta.sma(obv, length=10) if obv is not None else None

    signals = pd.Series(0, index=df.index)
    reasons = pd.Series("", index=df.index)

    for i in range(n):
        p = float(close.iloc[i])
        if p <= 0:
            continue

        # Momentum
        mom_score, mom_cnt = 0.0, 0
        s20 = _s(sma_20, i)
        s60 = _s(sma_60, i)
        if s20 is not None:
            mom_cnt += 1; mom_score += 0.5 if p > s20 else -0.5
        if s60 is not None:
            mom_cnt += 1; mom_score += 0.5 if p > s60 else -0.5
        mh = _s(macd_hist, i)
        if mh is not None:
            mom_cnt += 1; mom_score += 0.6 if mh > 0 else -0.6
        r = _s(rsi, i)
        if r is not None:
            mom_cnt += 1
            if 50 < r < 70: mom_score += 0.4
            elif 30 < r <= 50: mom_score -= 0.3
            elif r >= 70: mom_score += 0.2
            else: mom_score -= 0.5
        rc = _s(roc_12, i)
        if rc is not None:
            mom_cnt += 1
            if rc > 5: mom_score += 0.5
            elif rc > 0: mom_score += 0.2
            elif rc > -5: mom_score -= 0.2
            else: mom_score -= 0.5
        mom_final = mom_score / max(mom_cnt, 1)

        # Mean reversion
        mr_score, mr_cnt = 0.0, 0
        if r is not None:
            mr_cnt += 1
            if r < 30: mr_score += 0.8
            elif r > 70: mr_score -= 0.8
            elif r < 40: mr_score += 0.3
            elif r > 60: mr_score -= 0.3
        bbu, bbl = _s(bb_upper, i), _s(bb_lower, i)
        if bbu is not None and bbl is not None and bbu > bbl:
            mr_cnt += 1
            pos = (p - bbl) / (bbu - bbl)
            if pos < 0.2: mr_score += 0.7
            elif pos > 0.8: mr_score -= 0.7
            else: mr_score += (0.5 - pos) * 0.4
        sk = _s(stoch_k, i)
        if sk is not None:
            mr_cnt += 1
            if sk < 20: mr_score += 0.6
            elif sk > 80: mr_score -= 0.6
        wr = _s(willr, i)
        if wr is not None:
            mr_cnt += 1
            if wr < -80: mr_score += 0.5
            elif wr > -20: mr_score -= 0.5
        mr_final = mr_score / max(mr_cnt, 1)

        # Volume
        vol_score = 0.0
        vs20 = _s(vol_sma20, i)
        is_surge = vs20 is not None and vs20 > 0 and float(volume.iloc[i]) / vs20 > 2.0
        obv5 = _s(obv_sma5, i)
        obv10 = _s(obv_sma10, i)
        obv_inc = obv5 is not None and obv10 is not None and obv5 > obv10
        obv_dec = obv5 is not None and obv10 is not None and obv5 < obv10
        if is_surge and obv_inc: vol_score += 0.7
        elif is_surge and obv_dec: vol_score -= 0.5
        if i >= 5:
            price_chg = float(close.iloc[i]) - float(close.iloc[i - 5])
            vol_chg = float(volume.iloc[i]) - float(volume.iloc[i - 5])
            if price_chg < 0 and vol_chg > 0: vol_score += 0.4
            elif price_chg > 0 and vol_chg < 0: vol_score -= 0.4
        vs5 = _s(vol_sma5, i)
        if vs5 is not None and vs20 is not None and vs20 > 0:
            ratio = vs5 / vs20
            if ratio > 1.2: vol_score += 0.2
            elif ratio < 0.8: vol_score -= 0.1
        vol_final = max(-1.0, min(1.0, vol_score))

        # Ensemble
        ensemble = (
            mom_final * weights["momentum"]
            + mr_final * weights["mean_reversion"]
            + vol_final * weights["volume"]
        )
        ensemble = max(-1.0, min(1.0, ensemble))

        if ensemble > buy_threshold:
            signals.iloc[i] = 1
            factors = {"momentum": mom_final, "mean_reversion": mr_final, "volume": vol_final}
            top = max(factors, key=lambda k: factors[k])
            reasons.iloc[i] = f"{top}({ensemble:+.2f})"
        elif ensemble < sell_threshold:
            signals.iloc[i] = -1
            factors = {"momentum": mom_final, "mean_reversion": mr_final, "volume": vol_final}
            top = min(factors, key=lambda k: factors[k])
            reasons.iloc[i] = f"{top}({ensemble:+.2f})"

    return signals, reasons


def _s(series: pd.Series | None, idx: int):
    """Safe scalar access — returns None for NaN."""
    if series is None:
        return None
    v = series.iloc[idx]
    return None if pd.isna(v) else float(v)
