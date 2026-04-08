"""Backtest engine — orchestration layer.

Signal generation: app/strategy/backtest_signals.py
Trade simulation:  inline _simulate_trades (tightly coupled to equity tracking)
Helpers:           app/strategy/backtest_helpers.py
"""

import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd

from app.config import settings
from app.models.strategy import BacktestResult, BacktestTrade
from app.utils.market_calendar import KST

from app.strategy.backtest_signals import generate_backtest_signals
from app.strategy.backtest_helpers import (
    effective_slippage, snap_tick, is_entry_bar_allowed,
    fetch_kospi_benchmark, build_equity_series, build_monthly_returns,
    tick_size,
)

logger = logging.getLogger(__name__)

# Module-level defaults
BUY_FEE_RATE = 0.00015
SELL_FEE_RATE = 0.00015
SELL_TAX_RATE = 0.0018
SLIPPAGE_RATE = 0.0005
CAPITAL_FRACTION = 0.85
BACKTEST_MAX_DRAWDOWN_STOP = 0.08

# Re-exports for backward compatibility (walk_forward.py imports these)
_generate_backtest_signals = generate_backtest_signals
_effective_slippage = effective_slippage
_tick_size = tick_size
_snap_tick = snap_tick
_is_entry_bar_allowed = is_entry_bar_allowed
_s = lambda series, idx: None  # replaced by backtest_signals._s


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
    """Run backtest on historical OHLCV data."""
    now = datetime.now(timezone.utc)

    # Build query
    query = "SELECT time, open, high, low, close, volume FROM ohlcv WHERE stock_code = $1 AND interval = $2"
    params: list = [stock_code, interval]
    param_idx = 3
    if start_date:
        query += f" AND time >= ${param_idx}::timestamptz"
        params.append(datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc) if isinstance(start_date, str) else start_date)
        param_idx += 1
    if end_date:
        query += f" AND time <= ${param_idx}::timestamptz"
        ed = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if isinstance(end_date, str) else end_date
        params.append(ed)
        param_idx += 1
    query += " ORDER BY time ASC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    if len(rows) < 30:
        return BacktestResult(
            stock_code=stock_code, strategy=strategy, initial_capital=initial_capital,
            final_capital=initial_capital, period_bars=len(rows), total_return=0.0,
            max_drawdown=0.0, win_rate=0.0, total_trades=0,
            statistical_warnings=[f"데이터 {len(rows)}건 — 최소 30건 필요합니다."],
            trades=[], equity_curve=[], equity_series=[], trade_markers=[], monthly_returns=[],
            computed_at=now, start_date=start_date, end_date=end_date, interval=interval,
        )

    df = pd.DataFrame([dict(r) for r in rows])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    # Generate signals
    signals, reasons = generate_backtest_signals(df, strategy)

    # Simulate trades
    trades, equity_curve, bars_in_position = _simulate_trades(
        df, signals, reasons, initial_capital, interval=interval,
        buy_fee_rate=buy_fee_rate, sell_fee_rate=sell_fee_rate,
        sell_tax_rate=sell_tax_rate, slippage_rate=slippage_rate,
        capital_fraction=capital_fraction, max_drawdown_stop=max_drawdown_stop,
    )

    # Calculate metrics
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return = round((final_capital / initial_capital - 1) * 100, 2)

    peak = np.maximum.accumulate(equity_curve)
    peak = np.where(peak == 0, 1, peak)
    drawdown = (np.array(equity_curve) - peak) / peak
    max_dd = round(float(np.min(drawdown)) * 100, 2)

    sell_trades = [t for t in trades if t.action == "SELL"]
    profitable = sum(1 for t in sell_trades if t.pnl is not None and t.pnl > 0)
    win_rate = round(profitable / len(sell_trades) * 100, 2) if sell_trades else 0.0

    gross_profit = sum(float(t.pnl) for t in sell_trades if t.pnl is not None and t.pnl > 0)
    gross_loss = abs(sum(float(t.pnl) for t in sell_trades if t.pnl is not None and t.pnl < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    avg_trade_pnl = round(sum(float(t.pnl or 0) for t in sell_trades) / len(sell_trades), 0) if sell_trades else None
    holding_bars = [int(t.holding_bars) for t in sell_trades if t.holding_bars is not None]
    avg_holding_bars = round(sum(holding_bars) / len(holding_bars), 1) if holding_bars else None

    max_consecutive_losses = current_loss_streak = 0
    for trade in sell_trades:
        if trade.pnl is not None and trade.pnl < 0:
            current_loss_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_loss_streak = 0

    returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe = round(float(returns.mean() / returns.std() * np.sqrt(252)), 4) if len(returns) > 1 and returns.std() > 0 else None
    sortino = None
    if len(returns) > 1:
        downside = returns[returns < 0]
        downside_std = float(downside.std()) if len(downside) > 1 else 0.0
        if downside_std > 0:
            sortino = round(float(returns.mean() / downside_std * np.sqrt(252)), 4)

    days = len(df)
    annual_return = round(((final_capital / initial_capital) ** (252 / max(days, 1)) - 1) * 100, 2) if days > 0 and final_capital > 0 else None
    calmar = round(annual_return / abs(max_dd), 4) if annual_return is not None and max_dd < 0 else None

    # Benchmark
    benchmark_return = None
    kospi_series = None
    if benchmark == "none":
        pass
    elif benchmark == "kospi":
        kospi_series = await fetch_kospi_benchmark(pool, df)
        if kospi_series and len(kospi_series) > 1 and kospi_series[0] > 0:
            benchmark_return = round((kospi_series[-1] / kospi_series[0] - 1) * 100, 2)
        if benchmark_return is None and len(df) > 1 and float(df["close"].iloc[0]) > 0:
            benchmark_return = round((float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1) * 100, 2)
    else:
        if len(df) > 1 and float(df["close"].iloc[0]) > 0:
            benchmark_return = round((float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1) * 100, 2)

    expectancy = None
    if sell_trades:
        wins = [float(t.pnl) for t in sell_trades if t.pnl is not None and t.pnl > 0]
        losses = [abs(float(t.pnl)) for t in sell_trades if t.pnl is not None and t.pnl < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        wr = len(wins) / len(sell_trades)
        lr = len(losses) / len(sell_trades)
        expectancy = round(avg_win * wr - avg_loss * lr, 0)

    exposure_pct = round(bars_in_position / len(df) * 100, 2) if len(df) > 0 else None

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

    skip_bench = benchmark == "none"
    equity_series = build_equity_series(df, equity_curve, benchmark_return, None if skip_bench else kospi_series, skip_bench)
    trade_markers = [{"time": t.date, "action": t.action, "price": t.price} for t in trades]
    monthly_returns = build_monthly_returns(df, equity_curve)

    return BacktestResult(
        stock_code=stock_code, strategy=strategy, initial_capital=initial_capital,
        final_capital=round(final_capital, 0), period_bars=len(df),
        total_return=total_return, benchmark_return=benchmark_return,
        annual_return=annual_return, max_drawdown=max_dd,
        sharpe_ratio=sharpe, sortino_ratio=sortino, calmar_ratio=calmar,
        win_rate=win_rate, profit_factor=profit_factor,
        avg_trade_pnl=avg_trade_pnl, avg_holding_bars=avg_holding_bars,
        max_consecutive_losses=max_consecutive_losses,
        total_trades=len(trades), expectancy=expectancy, exposure_pct=exposure_pct,
        statistical_warnings=statistical_warnings,
        trades=trades, equity_curve=equity_curve,
        equity_series=equity_series, trade_markers=trade_markers, monthly_returns=monthly_returns,
        computed_at=now, start_date=start_date, end_date=end_date, interval=interval,
    )


def _simulate_trades(
    df: pd.DataFrame, signals: pd.Series, reasons: pd.Series, initial_capital: float, *,
    interval: str = "1d", buy_fee_rate: float = BUY_FEE_RATE, sell_fee_rate: float = SELL_FEE_RATE,
    sell_tax_rate: float = SELL_TAX_RATE, slippage_rate: float = SLIPPAGE_RATE,
    capital_fraction: float = CAPITAL_FRACTION, max_drawdown_stop: float = BACKTEST_MAX_DRAWDOWN_STOP,
) -> tuple[list[BacktestTrade], list[float], int]:
    """Simulate trades and track equity curve."""
    capital = initial_capital
    position = 0
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
        eff_slip = effective_slippage(open_price, bar_volume, slippage_rate)
        exec_price_buy = snap_tick(open_price * (1 + eff_slip), up=True)
        exec_price_sell = snap_tick(open_price * (1 - eff_slip), up=False)
        current_equity = capital + position * close_price
        peak_equity = max(peak_equity, current_equity)

        if peak_equity > 0 and current_equity <= peak_equity * (1 - max_drawdown_stop):
            blocked_until_next_day = True

        entry_allowed = (
            pending_signal == 1 and position == 0 and capital > exec_price_buy
            and not blocked_until_next_day and is_entry_bar_allowed(ts, interval)
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
                    trades.append(BacktestTrade(date=date, action="BUY", price=round(exec_price_buy, 2), quantity=quantity, reason=pending_reason or None))

        elif pending_signal == -1 and position > 0:
            gross_revenue = position * exec_price_sell
            fees = gross_revenue * sell_fee_rate
            taxes = gross_revenue * sell_tax_rate
            net_revenue = gross_revenue - fees - taxes
            pnl = round(net_revenue - position * avg_price, 0)
            holding_bars_val = max(i - entry_bar_index, 1) if entry_bar_index is not None else None
            capital += net_revenue
            trades.append(BacktestTrade(date=date, action="SELL", price=round(exec_price_sell, 2), quantity=position, pnl=pnl, holding_bars=holding_bars_val, reason=pending_reason or None))
            position = 0
            avg_price = 0.0
            entry_bar_index = None

        pending_signal = int(signals.iloc[i])
        pending_reason = str(reasons.iloc[i]) if reasons.iloc[i] else ""

        if position > 0:
            bars_in_position += 1

        equity = capital + position * close_price
        if day_start_equity > 0 and equity <= day_start_equity * (1 + settings.risk_max_daily_loss_pct):
            blocked_until_next_day = True
        equity_curve.append(round(equity, 0))

    # Close open position
    if position > 0:
        final_date = str(df["time"].iloc[-1])[:10]
        final_price = float(df["close"].iloc[-1]) * (1 - slippage_rate)
        gross_revenue = position * final_price
        net_revenue = gross_revenue - gross_revenue * sell_fee_rate - gross_revenue * sell_tax_rate
        pnl = round(net_revenue - position * avg_price, 0)
        holding_bars_val = max((len(df) - 1) - entry_bar_index, 1) if entry_bar_index is not None else None
        capital += net_revenue
        trades.append(BacktestTrade(date=final_date, action="SELL", price=round(final_price, 2), quantity=position, pnl=pnl, holding_bars=holding_bars_val, reason="position_close"))
        equity_curve[-1] = round(capital, 0)

    return trades, equity_curve, bars_in_position
