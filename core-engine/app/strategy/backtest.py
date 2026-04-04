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
        params.append(start_date)
        param_idx += 1
    if end_date:
        query += f" AND time <= ${param_idx}::timestamptz"
        params.append(end_date)
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

    # Benchmark return (buy and hold)
    benchmark_return = None
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
    equity_series = _build_equity_series(df, equity_curve, benchmark_return)

    # Build trade_markers
    trade_markers = [
        {"time": t.date, "action": t.action, "price": t.price}
        for t in trades
    ]

    # Build monthly_returns
    monthly_returns = _build_monthly_returns(df, equity_curve)

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
    """Generate buy/sell signals for backtesting.

    Returns:
        signals: Series with values: 1 (buy), -1 (sell), 0 (hold).
        reasons: Series with string reason for each signal.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    signals = pd.Series(0, index=df.index)
    reasons = pd.Series("", index=df.index)

    if strategy in ("ensemble", "momentum"):
        # SMA crossover
        sma_20 = ta.sma(close, length=20)
        sma_60 = ta.sma(close, length=60) if len(close) >= 60 else ta.sma(close, length=20)

        rsi = ta.rsi(close, length=14)
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)

        if sma_20 is not None and sma_60 is not None:
            # Golden cross = buy, death cross = sell
            prev_above = (sma_20.shift(1) > sma_60.shift(1))
            curr_above = (sma_20 > sma_60)
            golden_cross = curr_above & ~prev_above
            death_cross = ~curr_above & prev_above
            signals = signals.where(~golden_cross, 1)
            reasons = reasons.where(~golden_cross, "sma_golden_cross")
            signals = signals.where(~death_cross, -1)
            reasons = reasons.where(~death_cross, "sma_death_cross")

        # RSI filter
        if rsi is not None:
            rsi_oversold = rsi < 30
            rsi_overbought = rsi > 75
            signals = signals.where(~rsi_oversold, 1)
            reasons = reasons.where(~rsi_oversold, "rsi_oversold")
            signals = signals.where(~rsi_overbought, -1)
            reasons = reasons.where(~rsi_overbought, "rsi_overbought")

    elif strategy == "mean_reversion":
        bb = ta.bbands(close, length=20, std=2)
        rsi = ta.rsi(close, length=14)

        if bb is not None and rsi is not None:
            bb_lower = bb.iloc[:, 2]  # Lower band
            bb_upper = bb.iloc[:, 0]  # Upper band

            buy_cond = (close < bb_lower) & (rsi < 30)
            sell_cond = (close > bb_upper) & (rsi > 70)
            signals = signals.where(~buy_cond, 1)
            reasons = reasons.where(~buy_cond, "bb_lower_rsi")
            signals = signals.where(~sell_cond, -1)
            reasons = reasons.where(~sell_cond, "bb_upper_rsi")

    return signals, reasons


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
        date = str(df["time"].iloc[i])[:19]
        exec_price_buy = open_price * (1 + slippage_rate)
        exec_price_sell = open_price * (1 - slippage_rate)
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


def _build_equity_series(
    df: pd.DataFrame,
    equity_curve: list[float],
    benchmark_return: float | None,
) -> list[dict]:
    """Build equity series with actual timestamps, benchmark, and drawdown."""
    if not equity_curve or len(df) == 0:
        return []

    series = []
    first_close = float(df["close"].iloc[0])
    peak = equity_curve[0]

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

        # Benchmark: buy-and-hold normalized to same initial equity
        bench_val = None
        if first_close > 0:
            bench_val = round(equity_curve[0] * float(df["close"].iloc[i]) / first_close, 0)

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
