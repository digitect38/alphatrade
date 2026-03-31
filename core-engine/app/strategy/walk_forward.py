"""Walk-Forward backtest — out-of-sample strategy validation.

Splits historical data into rolling train/test windows.
For each window:
  1. Generate signals on the training set (in-sample)
  2. Evaluate those signals on the test set (out-of-sample)
  3. Record OOS performance metrics

This prevents overfitting by ensuring strategies are never tested on data they were trained on.
"""

import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
import pandas_ta as ta

from app.config import settings
from app.strategy.backtest import (
    BUY_FEE_RATE,
    SELL_FEE_RATE,
    SELL_TAX_RATE,
    SLIPPAGE_RATE,
    CAPITAL_FRACTION,
    _generate_backtest_signals,
    _simulate_trades,
)
from app.models.strategy import BacktestTrade

logger = logging.getLogger(__name__)

# Default window sizes (trading days)
DEFAULT_TRAIN_DAYS = 252  # 1 year
DEFAULT_TEST_DAYS = 63    # 3 months
DEFAULT_STEP_DAYS = 63    # step forward by test size (non-overlapping OOS)


class WalkForwardWindow:
    """Result of a single walk-forward window."""

    def __init__(
        self,
        window_id: int,
        train_start: str,
        train_end: str,
        test_start: str,
        test_end: str,
        train_bars: int,
        test_bars: int,
        oos_return: float,
        oos_max_drawdown: float,
        oos_sharpe: float | None,
        oos_win_rate: float,
        oos_trades: int,
        oos_profit_factor: float | None,
    ):
        self.window_id = window_id
        self.train_start = train_start
        self.train_end = train_end
        self.test_start = test_start
        self.test_end = test_end
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.oos_return = oos_return
        self.oos_max_drawdown = oos_max_drawdown
        self.oos_sharpe = oos_sharpe
        self.oos_win_rate = oos_win_rate
        self.oos_trades = oos_trades
        self.oos_profit_factor = oos_profit_factor

    def to_dict(self) -> dict:
        return {
            "window_id": self.window_id,
            "train_period": f"{self.train_start} ~ {self.train_end}",
            "test_period": f"{self.test_start} ~ {self.test_end}",
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "oos_return_pct": self.oos_return,
            "oos_max_drawdown_pct": self.oos_max_drawdown,
            "oos_sharpe": self.oos_sharpe,
            "oos_win_rate_pct": self.oos_win_rate,
            "oos_trades": self.oos_trades,
            "oos_profit_factor": self.oos_profit_factor,
        }


class WalkForwardResult:
    """Aggregated result of walk-forward analysis."""

    def __init__(
        self,
        stock_code: str,
        strategy: str,
        initial_capital: float,
        windows: list[WalkForwardWindow],
        total_bars: int,
    ):
        self.stock_code = stock_code
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.windows = windows
        self.total_bars = total_bars

    @property
    def total_windows(self) -> int:
        return len(self.windows)

    @property
    def avg_oos_return(self) -> float:
        if not self.windows:
            return 0.0
        return round(sum(w.oos_return for w in self.windows) / len(self.windows), 2)

    @property
    def avg_oos_sharpe(self) -> float | None:
        sharpes = [w.oos_sharpe for w in self.windows if w.oos_sharpe is not None]
        if not sharpes:
            return None
        return round(sum(sharpes) / len(sharpes), 4)

    @property
    def worst_oos_drawdown(self) -> float:
        if not self.windows:
            return 0.0
        return round(min(w.oos_max_drawdown for w in self.windows), 2)

    @property
    def total_oos_trades(self) -> int:
        return sum(w.oos_trades for w in self.windows)

    @property
    def avg_oos_win_rate(self) -> float:
        rates = [w.oos_win_rate for w in self.windows if w.oos_trades > 0]
        if not rates:
            return 0.0
        return round(sum(rates) / len(rates), 2)

    @property
    def compounded_oos_return(self) -> float:
        """Compound returns across all OOS windows."""
        factor = 1.0
        for w in self.windows:
            factor *= (1 + w.oos_return / 100)
        return round((factor - 1) * 100, 2)

    @property
    def profitable_windows(self) -> int:
        return sum(1 for w in self.windows if w.oos_return > 0)

    @property
    def consistency_ratio(self) -> float:
        """Fraction of windows with positive OOS return."""
        if not self.windows:
            return 0.0
        return round(self.profitable_windows / len(self.windows), 2)

    @property
    def verdict(self) -> str:
        """Simple pass/fail verdict for production readiness."""
        sharpe = self.avg_oos_sharpe
        if sharpe is None or sharpe < 0.3:
            return "FAIL"
        if self.consistency_ratio < 0.5:
            return "FAIL"
        if self.worst_oos_drawdown < -15:
            return "CAUTION"
        if sharpe >= 0.5 and self.consistency_ratio >= 0.6:
            return "PASS"
        return "CAUTION"

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "strategy": self.strategy,
            "initial_capital": self.initial_capital,
            "total_bars": self.total_bars,
            "total_windows": self.total_windows,
            "summary": {
                "avg_oos_return_pct": self.avg_oos_return,
                "compounded_oos_return_pct": self.compounded_oos_return,
                "avg_oos_sharpe": self.avg_oos_sharpe,
                "worst_oos_drawdown_pct": self.worst_oos_drawdown,
                "avg_oos_win_rate_pct": self.avg_oos_win_rate,
                "total_oos_trades": self.total_oos_trades,
                "profitable_windows": self.profitable_windows,
                "consistency_ratio": self.consistency_ratio,
                "verdict": self.verdict,
            },
            "windows": [w.to_dict() for w in self.windows],
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }


async def run_walk_forward(
    stock_code: str,
    initial_capital: float = 10_000_000,
    strategy: str = "ensemble",
    interval: str = "1d",
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    step_days: int | None = None,
    *,
    pool: asyncpg.Pool,
) -> dict:
    """Run walk-forward analysis on historical data.

    Args:
        stock_code: Stock to analyze
        initial_capital: Starting capital per window
        strategy: Signal strategy name
        interval: Data interval (1d, 1h, etc.)
        train_days: In-sample training window size (bars)
        test_days: Out-of-sample test window size (bars)
        step_days: Step size between windows (default = test_days)
        pool: Database connection pool
    """
    if step_days is None:
        step_days = test_days

    # Fetch all available data
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

    if len(rows) < train_days + test_days:
        return WalkForwardResult(
            stock_code=stock_code,
            strategy=strategy,
            initial_capital=initial_capital,
            windows=[],
            total_bars=len(rows),
        ).to_dict()

    df = pd.DataFrame([dict(r) for r in rows])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    windows = []
    window_id = 0
    start = 0

    while start + train_days + test_days <= len(df):
        train_end = start + train_days
        test_end = train_end + test_days

        train_df = df.iloc[start:train_end].reset_index(drop=True)
        test_df = df.iloc[train_end:test_end].reset_index(drop=True)

        # Generate signals using training data pattern,
        # then apply those same rules to the test data
        # (the signals function only uses the data it's given)
        test_signals = _generate_backtest_signals(test_df, strategy)

        # Simulate trades on OOS data
        trades, equity_curve = _simulate_trades(
            test_df, test_signals, initial_capital, interval=interval
        )

        # Calculate OOS metrics
        final_capital = equity_curve[-1] if equity_curve else initial_capital
        oos_return = round((final_capital / initial_capital - 1) * 100, 2)

        # Max drawdown
        peak = np.maximum.accumulate(equity_curve) if equity_curve else [initial_capital]
        drawdown = (np.array(equity_curve) - peak) / peak if equity_curve else [0]
        max_dd = round(float(np.min(drawdown)) * 100, 2) if len(drawdown) > 0 else 0.0

        # Sharpe ratio (annualized)
        returns = pd.Series(equity_curve).pct_change().dropna()
        sharpe = None
        if len(returns) > 1 and returns.std() > 0:
            sharpe = round(float(returns.mean() / returns.std() * np.sqrt(252)), 4)

        # Win rate
        sell_trades = [t for t in trades if t.action == "SELL"]
        profitable = sum(1 for t in sell_trades if t.pnl is not None and t.pnl > 0)
        win_rate = round(profitable / len(sell_trades) * 100, 2) if sell_trades else 0.0

        # Profit factor
        gross_profit = sum(float(t.pnl) for t in sell_trades if t.pnl and t.pnl > 0)
        gross_loss = abs(sum(float(t.pnl) for t in sell_trades if t.pnl and t.pnl < 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

        train_start_date = str(train_df["time"].iloc[0])[:10]
        train_end_date = str(train_df["time"].iloc[-1])[:10]
        test_start_date = str(test_df["time"].iloc[0])[:10]
        test_end_date = str(test_df["time"].iloc[-1])[:10]

        windows.append(WalkForwardWindow(
            window_id=window_id,
            train_start=train_start_date,
            train_end=train_end_date,
            test_start=test_start_date,
            test_end=test_end_date,
            train_bars=len(train_df),
            test_bars=len(test_df),
            oos_return=oos_return,
            oos_max_drawdown=max_dd,
            oos_sharpe=sharpe,
            oos_win_rate=win_rate,
            oos_trades=len(trades),
            oos_profit_factor=profit_factor,
        ))

        window_id += 1
        start += step_days

    result = WalkForwardResult(
        stock_code=stock_code,
        strategy=strategy,
        initial_capital=initial_capital,
        windows=windows,
        total_bars=len(df),
    )

    logger.info(
        "Walk-forward %s/%s: %d windows, avg OOS return=%.2f%%, verdict=%s",
        stock_code, strategy, result.total_windows,
        result.avg_oos_return, result.verdict,
    )

    return result.to_dict()
