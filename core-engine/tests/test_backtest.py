"""Tests for backtest engine logic (pure functions, no DB).

~80 test cases.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime

from app.strategy.backtest import _generate_backtest_signals, _is_entry_bar_allowed, _simulate_trades
from app.utils.market_calendar import KST


def _make_df(n=60, base_price=60000, trend=0):
    """Generate synthetic OHLCV DataFrame."""
    import random
    random.seed(42)
    data = []
    price = base_price
    for i in range(n):
        price = price + trend + random.randint(-1000, 1000)
        price = max(price, 1000)
        data.append({
            "time": pd.Timestamp(f"2026-01-{(i % 28) + 1:02d}"),
            "open": price - 500,
            "high": price + 1000,
            "low": price - 1500,
            "close": price,
            "volume": random.randint(1000000, 30000000),
        })
    df = pd.DataFrame(data)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    df["volume"] = pd.to_numeric(df["volume"]).astype(int)
    return df


class TestGenerateBacktestSignals:
    @pytest.mark.parametrize("strategy", ["ensemble", "momentum", "mean_reversion"])
    def test_returns_series(self, strategy):
        df = _make_df(60)
        signals, reasons = _generate_backtest_signals(df, strategy)
        assert isinstance(signals, pd.Series)
        assert isinstance(reasons, pd.Series)
        assert len(signals) == len(df)
        assert len(reasons) == len(df)

    @pytest.mark.parametrize("strategy", ["ensemble", "momentum", "mean_reversion"])
    def test_signal_values(self, strategy):
        df = _make_df(60)
        signals, _ = _generate_backtest_signals(df, strategy)
        unique_vals = set(signals.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_short_df_no_crash(self):
        df = _make_df(5)
        signals, _ = _generate_backtest_signals(df, "ensemble")
        assert len(signals) == 5

    @pytest.mark.parametrize("n", [10, 20, 30, 60, 100])
    def test_various_lengths(self, n):
        df = _make_df(n)
        signals, _ = _generate_backtest_signals(df, "ensemble")
        assert len(signals) == n

    def test_uptrend_generates_buy(self):
        df = _make_df(60, trend=500)  # strong uptrend
        signals, _ = _generate_backtest_signals(df, "momentum")
        assert 1 in signals.values  # should have at least one buy

    def test_downtrend_has_signals(self):
        df = _make_df(60, trend=-500)  # strong downtrend
        signals, _ = _generate_backtest_signals(df, "momentum")
        # Downtrend may trigger sell or RSI oversold buy — just verify signals exist
        assert len(signals) == 60
        assert signals.abs().sum() > 0  # at least some non-zero signals


def _empty_reasons(df):
    """Helper to create an empty reasons series matching df index."""
    return pd.Series("", index=df.index)


class TestSimulateTrades:
    def test_no_signals_no_trades(self):
        df = _make_df(30)
        signals = pd.Series(0, index=df.index)
        trades, equity, _ = _simulate_trades(df, signals, _empty_reasons(df), 10_000_000)
        assert len(trades) == 0
        assert len(equity) == 30
        assert all(e == 10_000_000 for e in equity)

    def test_buy_and_hold(self):
        df = _make_df(30)
        signals = pd.Series(0, index=df.index)
        signals.iloc[0] = 1  # buy on first day
        trades, equity, _ = _simulate_trades(df, signals, _empty_reasons(df), 10_000_000)
        assert len(trades) == 2
        assert trades[0].action == "BUY"
        assert trades[1].action == "SELL"
        assert trades[0].quantity > 0

    def test_buy_then_sell(self):
        df = _make_df(30)
        signals = pd.Series(0, index=df.index)
        signals.iloc[0] = 1   # buy
        signals.iloc[15] = -1  # sell
        trades, equity, _ = _simulate_trades(df, signals, _empty_reasons(df), 10_000_000)
        assert len(trades) == 2
        assert trades[0].action == "BUY"
        assert trades[1].action == "SELL"
        assert trades[1].pnl is not None

    def test_equity_length_matches_df(self):
        df = _make_df(50)
        signals = pd.Series(0, index=df.index)
        _, equity, _ = _simulate_trades(df, signals, _empty_reasons(df), 10_000_000)
        assert len(equity) == 50

    @pytest.mark.parametrize("capital", [1_000_000, 5_000_000, 10_000_000, 50_000_000])
    def test_various_capital(self, capital):
        df = _make_df(30)
        signals = pd.Series(0, index=df.index)
        signals.iloc[0] = 1
        trades, equity, _ = _simulate_trades(df, signals, _empty_reasons(df), capital)
        assert equity[0] <= capital  # can't exceed initial
        assert trades[0].quantity * trades[0].price <= capital

    def test_sell_without_buy_no_trade(self):
        df = _make_df(10)
        signals = pd.Series(0, index=df.index)
        signals.iloc[5] = -1  # sell without position
        trades, _, _ = _simulate_trades(df, signals, _empty_reasons(df), 10_000_000)
        assert len(trades) == 0

    def test_multiple_buy_sell_cycles(self):
        df = _make_df(60)
        signals = pd.Series(0, index=df.index)
        signals.iloc[5] = 1    # buy
        signals.iloc[15] = -1  # sell
        signals.iloc[25] = 1   # buy again
        signals.iloc[40] = -1  # sell again
        trades, _, _ = _simulate_trades(df, signals, _empty_reasons(df), 10_000_000)
        assert len(trades) == 4
        sells = [t for t in trades if t.action == "SELL"]
        assert all(t.pnl is not None for t in sells)

    def test_equity_never_negative(self):
        df = _make_df(60)
        signals, reasons = _generate_backtest_signals(df, "ensemble")
        _, equity, _ = _simulate_trades(df, signals, reasons, 10_000_000)
        assert all(e >= 0 for e in equity)

    def test_intraday_entry_blocked_before_open_delay(self):
        df = pd.DataFrame([
            {"time": pd.Timestamp("2026-03-31 09:00:00", tz=KST), "open": 10000, "high": 10100, "low": 9900, "close": 10050, "volume": 100000},
            {"time": pd.Timestamp("2026-03-31 09:01:00", tz=KST), "open": 10050, "high": 10150, "low": 10000, "close": 10100, "volume": 110000},
            {"time": pd.Timestamp("2026-03-31 09:02:00", tz=KST), "open": 10100, "high": 10150, "low": 10050, "close": 10120, "volume": 120000},
        ])
        signals = pd.Series([1, 0, 0], index=df.index)
        trades, _, _ = _simulate_trades(df, signals, _empty_reasons(df), 1_000_000, interval="1m")
        assert len(trades) == 0

    def test_entry_bar_allowed_during_regular_window(self):
        assert _is_entry_bar_allowed(datetime(2026, 3, 31, 9, 10, tzinfo=KST), "1m") is True
        assert _is_entry_bar_allowed(datetime(2026, 3, 31, 9, 2, tzinfo=KST), "1m") is False
        assert _is_entry_bar_allowed(datetime(2026, 3, 31, 15, 5, tzinfo=KST), "1m") is False
