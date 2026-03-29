import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
import pandas_ta as ta
from app.models.strategy import BacktestResult, BacktestTrade

logger = logging.getLogger(__name__)


async def run_backtest(
    stock_code: str,
    initial_capital: float = 10_000_000,
    strategy: str = "ensemble",
    interval: str = "1d",
    *,
    pool: asyncpg.Pool,
) -> BacktestResult:
    """Run backtest on historical OHLCV data using a simple strategy."""
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, open, high, low, close, volume
            FROM ohlcv
            WHERE stock_code = $1 AND interval = $2
            ORDER BY time ASC
            """,
            stock_code,
            interval,
        )

    if len(rows) < 30:
        return BacktestResult(
            stock_code=stock_code,
            strategy=strategy,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            total_trades=0,
            computed_at=now,
        )

    df = pd.DataFrame([dict(r) for r in rows])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    # Generate signals based on strategy
    signals = _generate_backtest_signals(df, strategy)

    # Simulate trading
    trades, equity_curve = _simulate_trades(df, signals, initial_capital)

    # Calculate performance metrics
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return = round((final_capital / initial_capital - 1) * 100, 2)

    # Max drawdown
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (np.array(equity_curve) - peak) / peak
    max_dd = round(float(np.min(drawdown)) * 100, 2)

    # Win rate
    profitable = sum(1 for t in trades if t.pnl and t.pnl > 0)
    sell_trades = sum(1 for t in trades if t.action == "SELL")
    win_rate = round(profitable / sell_trades * 100, 2) if sell_trades > 0 else 0.0

    # Sharpe ratio (annualized)
    returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe = None
    if len(returns) > 1 and returns.std() > 0:
        sharpe = round(float(returns.mean() / returns.std() * np.sqrt(252)), 4)

    # Annual return
    days = len(df)
    annual_return = None
    if days > 0 and final_capital > 0:
        annual_return = round(((final_capital / initial_capital) ** (252 / max(days, 1)) - 1) * 100, 2)

    return BacktestResult(
        stock_code=stock_code,
        strategy=strategy,
        initial_capital=initial_capital,
        final_capital=round(final_capital, 0),
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        win_rate=win_rate,
        total_trades=len(trades),
        trades=trades[-20:],  # Last 20 trades
        equity_curve=equity_curve[-60:],  # Last 60 points
        computed_at=now,
    )


def _generate_backtest_signals(df: pd.DataFrame, strategy: str) -> pd.Series:
    """Generate buy/sell signals for backtesting.

    Returns Series with values: 1 (buy), -1 (sell), 0 (hold).
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    signals = pd.Series(0, index=df.index)

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
            signals = signals.where(~(curr_above & ~prev_above), 1)   # golden cross
            signals = signals.where(~(~curr_above & prev_above), -1)  # death cross

        # RSI filter
        if rsi is not None:
            signals = signals.where(~(rsi < 30), 1)   # oversold buy
            signals = signals.where(~(rsi > 75), -1)  # overbought sell

    elif strategy == "mean_reversion":
        bb = ta.bbands(close, length=20, std=2)
        rsi = ta.rsi(close, length=14)

        if bb is not None and rsi is not None:
            bb_lower = bb.iloc[:, 2]  # Lower band
            bb_upper = bb.iloc[:, 0]  # Upper band

            signals = signals.where(~((close < bb_lower) & (rsi < 30)), 1)
            signals = signals.where(~((close > bb_upper) & (rsi > 70)), -1)

    return signals


def _simulate_trades(
    df: pd.DataFrame, signals: pd.Series, initial_capital: float
) -> tuple[list[BacktestTrade], list[float]]:
    """Simulate trades and track equity curve."""
    capital = initial_capital
    position = 0  # shares held
    avg_price = 0.0
    trades = []
    equity_curve = []

    for i in range(len(df)):
        price = float(df["close"].iloc[i])
        date = str(df["time"].iloc[i])[:10]
        sig = int(signals.iloc[i])

        if sig == 1 and position == 0 and capital > price:
            # Buy: invest 90% of capital
            invest = capital * 0.9
            quantity = int(invest / price)
            if quantity > 0:
                cost = quantity * price
                capital -= cost
                position = quantity
                avg_price = price
                trades.append(BacktestTrade(date=date, action="BUY", price=price, quantity=quantity))

        elif sig == -1 and position > 0:
            # Sell all
            revenue = position * price
            pnl = round(revenue - position * avg_price, 0)
            capital += revenue
            trades.append(BacktestTrade(date=date, action="SELL", price=price, quantity=position, pnl=pnl))
            position = 0
            avg_price = 0.0

        # Track equity
        equity = capital + position * price
        equity_curve.append(round(equity, 0))

    return trades, equity_curve
