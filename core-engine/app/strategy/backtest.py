import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
import pandas_ta as ta
from app.config import settings
from app.models.strategy import BacktestResult, BacktestTrade
from app.utils.market_calendar import KST, MarketSession, get_current_session

logger = logging.getLogger(__name__)

# Module-level defaults (kept for backward compat / walk-forward usage)
BUY_FEE_RATE = 0.00015
SELL_FEE_RATE = 0.00015
SELL_TAX_RATE = 0.0018
SLIPPAGE_RATE = 0.0005
CAPITAL_FRACTION = 0.85
BACKTEST_MAX_DRAWDOWN_STOP = 0.08


async def run_backtest(
    stock_code: str,
    initial_capital: float = 10_000_000,
    strategy: str = "ensemble",
    interval: str = "1d",
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    buy_fee_rate: float = BUY_FEE_RATE,
    sell_fee_rate: float = SELL_FEE_RATE,
    sell_tax_rate: float = SELL_TAX_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
    capital_fraction: float = CAPITAL_FRACTION,
    max_drawdown_stop: float = BACKTEST_MAX_DRAWDOWN_STOP,
    benchmark: str = "buy_and_hold",
    pool: asyncpg.Pool,
) -> BacktestResult:
    """Run backtest on historical OHLCV data using a simple strategy."""
    now = datetime.now(timezone.utc)

    # Build query with optional date filtering
    query = """
        SELECT time, open, high, low, close, volume
        FROM ohlcv
        WHERE stock_code = $1 AND interval = $2
    """
    params: list = [stock_code, interval]
    param_idx = 3

    if start_date:
        query += f" AND time >= ${param_idx}::timestamptz"
        params.append(datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc) if isinstance(start_date, str) else start_date)
        param_idx += 1
    if end_date:
        query += f" AND time <= ${param_idx}::timestamptz"
        # End date should include the full day
        ed = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if isinstance(end_date, str) else end_date
        params.append(ed)
        param_idx += 1

    query += " ORDER BY time ASC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    if len(rows) < 30:
        return BacktestResult(
            stock_code=stock_code,
            strategy=strategy,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            period_bars=len(rows),
            total_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            total_trades=0,
            statistical_warnings=[f"데이터 {len(rows)}건 — 최소 30건 필요합니다."],
            trades=[],
            equity_curve=[],
            equity_series=[],
            trade_markers=[],
            monthly_returns=[],
            computed_at=now,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

    df = pd.DataFrame([dict(r) for r in rows])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    # Generate signals based on strategy
    signals, reasons = _generate_backtest_signals(df, strategy)

    # Simulate trading
    trades, equity_curve, bars_in_position = _simulate_trades(
        df, signals, reasons, initial_capital,
        interval=interval,
        buy_fee_rate=buy_fee_rate,
        sell_fee_rate=sell_fee_rate,
        sell_tax_rate=sell_tax_rate,
        slippage_rate=slippage_rate,
        capital_fraction=capital_fraction,
        max_drawdown_stop=max_drawdown_stop,
    )

    # Calculate performance metrics
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return = round((final_capital / initial_capital - 1) * 100, 2)

    # Max drawdown
    peak = np.maximum.accumulate(equity_curve)
    peak = np.where(peak == 0, 1, peak)  # avoid div-by-zero
    drawdown = (np.array(equity_curve) - peak) / peak
    max_dd = round(float(np.min(drawdown)) * 100, 2)

    sell_trades = [t for t in trades if t.action == "SELL"]
    profitable = sum(1 for t in sell_trades if t.pnl is not None and t.pnl > 0)
    win_rate = round(profitable / len(sell_trades) * 100, 2) if sell_trades else 0.0

    gross_profit = sum(float(t.pnl) for t in sell_trades if t.pnl is not None and t.pnl > 0)
    gross_loss = abs(sum(float(t.pnl) for t in sell_trades if t.pnl is not None and t.pnl < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    avg_trade_pnl = None
    if sell_trades:
        avg_trade_pnl = round(sum(float(t.pnl or 0) for t in sell_trades) / len(sell_trades), 0)

    holding_bars = [int(t.holding_bars) for t in sell_trades if t.holding_bars is not None]
    avg_holding_bars = round(sum(holding_bars) / len(holding_bars), 1) if holding_bars else None

    max_consecutive_losses = 0
    current_loss_streak = 0
    for trade in sell_trades:
        if trade.pnl is not None and trade.pnl < 0:
            current_loss_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_loss_streak = 0

    # Sharpe ratio (annualized)
    returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe = None
    if len(returns) > 1 and returns.std() > 0:
        sharpe = round(float(returns.mean() / returns.std() * np.sqrt(252)), 4)

    # Sortino ratio (annualized, downside deviation only)
    sortino = None
    if len(returns) > 1:
        downside = returns[returns < 0]
        downside_std = float(downside.std()) if len(downside) > 1 else 0.0
        if downside_std > 0:
            sortino = round(float(returns.mean() / downside_std * np.sqrt(252)), 4)

    # Annual return
    days = len(df)
    annual_return = None
    if days > 0 and final_capital > 0:
        annual_return = round(((final_capital / initial_capital) ** (252 / max(days, 1)) - 1) * 100, 2)

    # Calmar ratio: annual_return / |max_drawdown|
    calmar = None
    if annual_return is not None and max_dd < 0:
        calmar = round(annual_return / abs(max_dd), 4)

    # Benchmark return
    benchmark_return = None
    kospi_series: list[float] | None = None
    if benchmark == "none":
        pass  # No benchmark
    elif benchmark == "kospi":
        kospi_series = await _fetch_kospi_benchmark(pool, df)
        if kospi_series and len(kospi_series) > 1 and kospi_series[0] > 0:
            benchmark_return = round((kospi_series[-1] / kospi_series[0] - 1) * 100, 2)
        if benchmark_return is None and len(df) > 1 and float(df["close"].iloc[0]) > 0:
            benchmark_return = round((float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1) * 100, 2)
    else:
        # Default: buy-and-hold of the stock itself
        if len(df) > 1 and float(df["close"].iloc[0]) > 0:
            benchmark_return = round((float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1) * 100, 2)

    # Expectancy: (avg_win * win_rate) - (avg_loss * loss_rate)
    expectancy = None
    if sell_trades:
        wins = [float(t.pnl) for t in sell_trades if t.pnl is not None and t.pnl > 0]
        losses = [abs(float(t.pnl)) for t in sell_trades if t.pnl is not None and t.pnl < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        wr = len(wins) / len(sell_trades)
        lr = len(losses) / len(sell_trades)
        expectancy = round(avg_win * wr - avg_loss * lr, 0)

    # Exposure %: bars with position / total bars
    exposure_pct = None
    total_bars = len(df)
    if total_bars > 0:
        exposure_pct = round(bars_in_position / total_bars * 100, 2)

    # Build equity_series with actual timestamps
    skip_bench = benchmark == "none"
    equity_series = _build_equity_series(df, equity_curve, benchmark_return, None if skip_bench else kospi_series, skip_bench)

    # Build trade_markers
    trade_markers = [
        {"time": t.date, "action": t.action, "price": t.price}
        for t in trades
    ]

    # Build monthly_returns
    monthly_returns = _build_monthly_returns(df, equity_curve)

    # Statistical warnings
    statistical_warnings = []
    if len(sell_trades) < 5:
        statistical_warnings.append("거래 수 5건 미만 — 모든 지표가 통계적으로 무의미합니다.")
    elif len(sell_trades) < 30:
        statistical_warnings.append(f"거래 수 {len(sell_trades)}건 — Sharpe/Sortino/승률 등의 신뢰도가 낮습니다 (최소 30건 권장).")
    if days < 60:
        statistical_warnings.append(f"분석 기간 {days}일 — 시장 사이클을 반영하기에 너무 짧습니다 (최소 1년 권장).")
    if exposure_pct is not None and exposure_pct < 5:
        statistical_warnings.append(f"투자 노출도 {exposure_pct:.1f}% — 거의 현금 보유 상태이므로 수익률 해석에 주의하세요.")

    return BacktestResult(
        stock_code=stock_code,
        strategy=strategy,
        initial_capital=initial_capital,
        final_capital=round(final_capital, 0),
        period_bars=len(df),
        total_return=total_return,
        benchmark_return=benchmark_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_trade_pnl=avg_trade_pnl,
        avg_holding_bars=avg_holding_bars,
        max_consecutive_losses=max_consecutive_losses,
        total_trades=len(trades),
        expectancy=expectancy,
        exposure_pct=exposure_pct,
        statistical_warnings=statistical_warnings,
        trades=trades,                     # ALL trades
        equity_curve=equity_curve,         # ALL points
        equity_series=equity_series,
        trade_markers=trade_markers,
        monthly_returns=monthly_returns,
        computed_at=now,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )


def _generate_backtest_signals(df: pd.DataFrame, strategy: str) -> tuple[pd.Series, pd.Series]:
    """Generate buy/sell signals using the PRODUCTION ensemble engine.

    Replicates the 4-factor weighted scoring from signals.py + presets.py:
      momentum_signal()  — SMA, MACD, RSI-momentum, ROC
      mean_reversion_signal() — RSI-reversal, BB position, Stochastic, Williams%R
      volume_signal()    — surge detection, OBV, price-volume divergence
      sentiment = 0      — no historical sentiment in backtest context

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

    # ── Pre-compute all technical indicators vectorised ──
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

    # Volume indicators
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

        # ── Momentum score (averaged) ──
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

        # ── Mean reversion score (averaged) ──
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

        # ── Volume score (cumulative, clamped) ──
        vol_score = 0.0
        vs5 = _s(vol_sma5, i)
        vs20 = _s(vol_sma20, i)
        is_surge = vs20 is not None and vs20 > 0 and float(volume.iloc[i]) / vs20 > 2.0
        obv5 = _s(obv_sma5, i)
        obv10 = _s(obv_sma10, i)
        obv_inc = obv5 is not None and obv10 is not None and obv5 > obv10
        obv_dec = obv5 is not None and obv10 is not None and obv5 < obv10
        if is_surge and obv_inc: vol_score += 0.7
        elif is_surge and obv_dec: vol_score -= 0.5
        # Price-volume divergence (5-bar lookback)
        if i >= 5:
            price_chg = float(close.iloc[i]) - float(close.iloc[i - 5])
            vol_chg = float(volume.iloc[i]) - float(volume.iloc[i - 5])
            if price_chg < 0 and vol_chg > 0: vol_score += 0.4   # bullish div
            elif price_chg > 0 and vol_chg < 0: vol_score -= 0.4  # bearish div
        if vs5 is not None and vs20 is not None and vs20 > 0:
            ratio = vs5 / vs20
            if ratio > 1.2: vol_score += 0.2
            elif ratio < 0.8: vol_score -= 0.1
        vol_final = max(-1.0, min(1.0, vol_score))

        # ── Ensemble ──
        ensemble = (
            mom_final * weights["momentum"]
            + mr_final * weights["mean_reversion"]
            + vol_final * weights["volume"]
            # sentiment = 0 (no historical sentiment data)
        )
        ensemble = max(-1.0, min(1.0, ensemble))

        if ensemble > buy_threshold:
            signals.iloc[i] = 1
            # Pick dominant factor
            factors = {"momentum": mom_final, "mean_reversion": mr_final, "volume": vol_final}
            top = max(factors, key=lambda k: factors[k])
            reasons.iloc[i] = f"{top}({ensemble:+.2f})"
        elif ensemble < sell_threshold:
            signals.iloc[i] = -1
            factors = {"momentum": mom_final, "mean_reversion": mr_final, "volume": vol_final}
            top = min(factors, key=lambda k: factors[k])
            reasons.iloc[i] = f"{top}({ensemble:+.2f})"

    return signals, reasons


def _effective_slippage(price: float, bar_volume: float, base_rate: float) -> float:
    """Volume-aware slippage: illiquid bars get higher slippage.

    - If bar volume < 10,000 shares → 3× base rate (illiquid)
    - If bar volume < 50,000 shares → 1.5× base rate
    - Otherwise → base rate
    Also floors at 1 tick to avoid zero-slippage illusion.
    """
    if bar_volume <= 0:
        return base_rate * 3
    if bar_volume < 10_000:
        return base_rate * 3
    if bar_volume < 50_000:
        return base_rate * 1.5
    return base_rate


def _tick_size(price: float) -> float:
    """Korean stock market tick size rules (KRX 호가 단위)."""
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def _snap_tick(price: float, up: bool = True) -> float:
    """Snap price to nearest valid tick. up=True rounds up (buy), up=False rounds down (sell)."""
    import math
    tick = _tick_size(price)
    if up:
        return float(math.ceil(price / tick) * tick)
    return float(math.floor(price / tick) * tick)


def _s(series: pd.Series | None, idx: int):
    """Safe scalar access — returns None for NaN."""
    if series is None:
        return None
    v = series.iloc[idx]
    return None if pd.isna(v) else float(v)


def _simulate_trades(
    df: pd.DataFrame,
    signals: pd.Series,
    reasons: pd.Series,
    initial_capital: float,
    *,
    interval: str = "1d",
    buy_fee_rate: float = BUY_FEE_RATE,
    sell_fee_rate: float = SELL_FEE_RATE,
    sell_tax_rate: float = SELL_TAX_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
    capital_fraction: float = CAPITAL_FRACTION,
    max_drawdown_stop: float = BACKTEST_MAX_DRAWDOWN_STOP,
) -> tuple[list[BacktestTrade], list[float], int]:
    """Simulate trades and track equity curve.

    Returns (trades, equity_curve, bars_in_position).
    """
    capital = initial_capital
    position = 0  # shares held
    avg_price = 0.0
    entry_bar_index: int | None = None
    trades: list[BacktestTrade] = []
    equity_curve: list[float] = []
    pending_signal = 0
    pending_reason = ""
    peak_equity = initial_capital
    blocked_until_next_day = False
    current_day = None
    day_start_equity = initial_capital
    bars_in_position = 0

    for i in range(len(df)):
        ts = pd.Timestamp(df["time"].iloc[i]).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        else:
            ts = ts.astimezone(KST)

        bar_day = ts.date()
        if current_day != bar_day:
            current_day = bar_day
            day_start_equity = capital + position * float(df["close"].iloc[i])
            blocked_until_next_day = False

        open_price = float(df["open"].iloc[i])
        close_price = float(df["close"].iloc[i])
        bar_volume = float(df["volume"].iloc[i]) if df["volume"].iloc[i] else 0
        date = str(df["time"].iloc[i])[:19]
        # Volume-aware slippage: base rate + impact for illiquid bars
        eff_slip = _effective_slippage(open_price, bar_volume, slippage_rate)
        exec_price_buy = _snap_tick(open_price * (1 + eff_slip), up=True)
        exec_price_sell = _snap_tick(open_price * (1 - eff_slip), up=False)
        current_equity = capital + position * close_price
        peak_equity = max(peak_equity, current_equity)

        if peak_equity > 0 and current_equity <= peak_equity * (1 - max_drawdown_stop):
            blocked_until_next_day = True

        # Execute the previous bar's signal on this bar's open.
        entry_allowed = (
            pending_signal == 1
            and position == 0
            and capital > exec_price_buy
            and not blocked_until_next_day
            and _is_entry_bar_allowed(ts, interval)
        )
        if entry_allowed:
            invest = capital * capital_fraction
            quantity = int(invest / exec_price_buy)
            if quantity > 0:
                gross_cost = quantity * exec_price_buy
                fees = gross_cost * buy_fee_rate
                total_cost = gross_cost + fees
                if total_cost > capital:
                    quantity = int(capital / (exec_price_buy * (1 + buy_fee_rate)))
                    gross_cost = quantity * exec_price_buy
                    fees = gross_cost * buy_fee_rate
                    total_cost = gross_cost + fees
                if quantity > 0 and total_cost <= capital:
                    capital -= total_cost
                    position = quantity
                    avg_price = (gross_cost + fees) / quantity
                    entry_bar_index = i
                    trades.append(BacktestTrade(
                        date=date,
                        action="BUY",
                        price=round(exec_price_buy, 2),
                        quantity=quantity,
                        reason=pending_reason or None,
                    ))

        elif pending_signal == -1 and position > 0:
            gross_revenue = position * exec_price_sell
            fees = gross_revenue * sell_fee_rate
            taxes = gross_revenue * sell_tax_rate
            net_revenue = gross_revenue - fees - taxes
            pnl = round(net_revenue - position * avg_price, 0)
            holding_bars_val = max(i - entry_bar_index, 1) if entry_bar_index is not None else None
            capital += net_revenue
            trades.append(BacktestTrade(
                date=date,
                action="SELL",
                price=round(exec_price_sell, 2),
                quantity=position,
                pnl=pnl,
                holding_bars=holding_bars_val,
                reason=pending_reason or None,
            ))
            position = 0
            avg_price = 0.0
            entry_bar_index = None

        pending_signal = int(signals.iloc[i])
        pending_reason = str(reasons.iloc[i]) if reasons.iloc[i] else ""

        # Track position exposure
        if position > 0:
            bars_in_position += 1

        # Track equity using the close, not the open execution price.
        equity = capital + position * close_price
        if day_start_equity > 0 and equity <= day_start_equity * (1 + settings.risk_max_daily_loss_pct):
            blocked_until_next_day = True
        equity_curve.append(round(equity, 0))

    # Resolve final open position at the last close with conservative costs.
    if position > 0:
        final_date = str(df["time"].iloc[-1])[:10]
        final_price = float(df["close"].iloc[-1]) * (1 - slippage_rate)
        gross_revenue = position * final_price
        fees = gross_revenue * sell_fee_rate
        taxes = gross_revenue * sell_tax_rate
        net_revenue = gross_revenue - fees - taxes
        pnl = round(net_revenue - position * avg_price, 0)
        holding_bars_val = max((len(df) - 1) - entry_bar_index, 1) if entry_bar_index is not None else None
        capital += net_revenue
        trades.append(BacktestTrade(
            date=final_date,
            action="SELL",
            price=round(final_price, 2),
            quantity=position,
            pnl=pnl,
            holding_bars=holding_bars_val,
            reason="position_close",
        ))
        position = 0
        avg_price = 0.0
        entry_bar_index = None
        equity_curve[-1] = round(capital, 0)

    return trades, equity_curve, bars_in_position


async def _fetch_kospi_benchmark(pool: asyncpg.Pool, df: pd.DataFrame) -> list[float] | None:
    """Fetch KOSPI closing prices aligned to the stock's date range."""
    if len(df) == 0:
        return None
    first_date = pd.Timestamp(df["time"].iloc[0]).to_pydatetime()
    last_date = pd.Timestamp(df["time"].iloc[-1]).to_pydatetime()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT time::date as dt, close FROM ohlcv "
                "WHERE stock_code = 'KOSPI' AND interval = '1d' "
                "AND time >= $1 AND time <= $2 ORDER BY time ASC",
                first_date, last_date,
            )
        if len(rows) < 2:
            return None
        # Build date→close map
        kospi_map = {str(r["dt"]): float(r["close"]) for r in rows if r["close"]}
        # Align to stock dates (forward fill missing)
        result = []
        last_val = None
        for i in range(len(df)):
            dt_str = str(pd.Timestamp(df["time"].iloc[i]).date())
            if dt_str in kospi_map:
                last_val = kospi_map[dt_str]
            if last_val is not None:
                result.append(last_val)
            else:
                result.append(0.0)
        return result if any(v > 0 for v in result) else None
    except Exception:
        return None


def _build_equity_series(
    df: pd.DataFrame,
    equity_curve: list[float],
    benchmark_return: float | None,
    kospi_series: list[float] | None = None,
    skip_benchmark: bool = False,
) -> list[dict]:
    """Build equity series with actual timestamps, benchmark, and drawdown."""
    if not equity_curve or len(df) == 0:
        return []

    series = []
    first_close = float(df["close"].iloc[0])
    initial_equity = equity_curve[0]
    peak = initial_equity

    # Determine benchmark source
    use_kospi = kospi_series is not None and len(kospi_series) == len(equity_curve)
    kospi_base = kospi_series[0] if use_kospi and kospi_series[0] > 0 else 0.0

    for i in range(len(equity_curve)):
        ts = pd.Timestamp(df["time"].iloc[i]).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        else:
            ts = ts.astimezone(KST)
        time_str = ts.isoformat()

        equity_val = equity_curve[i]
        peak = max(peak, equity_val)
        dd = round((equity_val - peak) / peak * 100, 4) if peak > 0 else 0.0

        # Benchmark: KOSPI or buy-and-hold, normalized to initial equity
        bench_val = None
        if not skip_benchmark:
            if use_kospi and kospi_base > 0:
                bench_val = round(initial_equity * kospi_series[i] / kospi_base, 0)
            elif first_close > 0:
                bench_val = round(initial_equity * float(df["close"].iloc[i]) / first_close, 0)

        series.append({
            "time": time_str,
            "equity": equity_val,
            "benchmark": bench_val,
            "drawdown": dd,
        })

    return series


def _build_monthly_returns(df: pd.DataFrame, equity_curve: list[float]) -> list[dict]:
    """Group equity changes by month to build monthly return series."""
    if not equity_curve or len(df) == 0:
        return []

    monthly: dict[str, tuple[float, float]] = {}  # month -> (first_equity, last_equity)

    for i in range(len(equity_curve)):
        ts = pd.Timestamp(df["time"].iloc[i]).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        else:
            ts = ts.astimezone(KST)
        month_key = ts.strftime("%Y-%m")
        eq = equity_curve[i]

        if month_key not in monthly:
            # Use previous month's last equity as start, or first equity if first month
            monthly[month_key] = (eq, eq)
        else:
            monthly[month_key] = (monthly[month_key][0], eq)

    result = []
    prev_end = None
    for month_key in sorted(monthly.keys()):
        first_eq, last_eq = monthly[month_key]
        base = prev_end if prev_end is not None else first_eq
        ret_pct = round((last_eq / base - 1) * 100, 2) if base > 0 else 0.0
        result.append({"month": month_key, "return_pct": ret_pct})
        prev_end = last_eq

    return result


def _is_entry_bar_allowed(ts: datetime, interval: str) -> bool:
    """Apply lightweight session gating for intraday backtests.

    Daily bars have no intra-session timing information, so they are always allowed.
    """
    if interval == "1d":
        return True

    session, _ = get_current_session(ts.astimezone(KST))
    if session != MarketSession.REGULAR:
        return False

    current_time = ts.astimezone(KST).time()
    open_with_delay = datetime.strptime(
        f"09:{settings.risk_session_open_delay_min:02d}",
        "%H:%M",
    ).time()

    close_buffer_hour = 15
    close_buffer_min = 20 - settings.risk_session_close_buffer_min
    if close_buffer_min < 0:
        close_buffer_hour = 14
        close_buffer_min = 60 + close_buffer_min
    close_with_buffer = datetime.strptime(
        f"{close_buffer_hour:02d}:{close_buffer_min:02d}",
        "%H:%M",
    ).time()

    return open_with_delay <= current_time < close_with_buffer
