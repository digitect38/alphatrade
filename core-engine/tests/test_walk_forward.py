"""Tests for walk-forward backtest engine."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.strategy.walk_forward import (
    WalkForwardResult,
    WalkForwardWindow,
    run_walk_forward,
    DEFAULT_TRAIN_DAYS,
    DEFAULT_TEST_DAYS,
)


def _make_ohlcv_rows(n_bars: int, start_price: float = 50000) -> list[dict]:
    """Generate synthetic OHLCV rows for testing."""
    import random
    random.seed(42)
    rows = []
    price = start_price
    base_time = datetime(2021, 1, 4, tzinfo=timezone.utc)

    for i in range(n_bars):
        change = random.uniform(-0.03, 0.035) * price
        price = max(price + change, 1000)
        o = price * random.uniform(0.99, 1.01)
        h = price * random.uniform(1.0, 1.03)
        l = price * random.uniform(0.97, 1.0)
        vol = random.randint(100000, 2000000)

        rows.append({
            "time": base_time + timedelta(days=i),
            "open": Decimal(str(round(o, 0))),
            "high": Decimal(str(round(h, 0))),
            "low": Decimal(str(round(l, 0))),
            "close": Decimal(str(round(price, 0))),
            "volume": vol,
        })
    return rows


class MockPool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return MockAcquire(self._rows)


class MockAcquire:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return MockConn(self._rows)

    async def __aexit__(self, *args):
        pass


class MockConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


@pytest.mark.asyncio
async def test_walk_forward_insufficient_data():
    """Walk-forward with insufficient data returns empty windows."""
    rows = _make_ohlcv_rows(100)  # Too few for train(252) + test(63)
    pool = MockPool(rows)

    result = await run_walk_forward(
        stock_code="005930",
        initial_capital=10_000_000,
        strategy="ensemble",
        pool=pool,
    )

    assert result["total_windows"] == 0
    assert result["total_bars"] == 100


@pytest.mark.asyncio
async def test_walk_forward_single_window():
    """Walk-forward with exactly enough data for 1 window."""
    rows = _make_ohlcv_rows(315 + 10)  # 252 + 63 + a bit
    pool = MockPool(rows)

    result = await run_walk_forward(
        stock_code="005930",
        initial_capital=10_000_000,
        strategy="ensemble",
        pool=pool,
    )

    assert result["total_windows"] == 1
    window = result["windows"][0]
    assert window["train_bars"] == 252
    assert window["test_bars"] == 63
    assert "oos_return_pct" in window
    assert "oos_sharpe" in window


@pytest.mark.asyncio
async def test_walk_forward_multiple_windows():
    """Walk-forward with enough data for multiple windows."""
    rows = _make_ohlcv_rows(800)  # Enough for ~8 windows
    pool = MockPool(rows)

    result = await run_walk_forward(
        stock_code="005930",
        initial_capital=10_000_000,
        strategy="momentum",
        train_days=100,
        test_days=50,
        pool=pool,
    )

    assert result["total_windows"] > 1
    assert result["strategy"] == "momentum"
    assert "summary" in result
    summary = result["summary"]
    assert "avg_oos_return_pct" in summary
    assert "compounded_oos_return_pct" in summary
    assert "consistency_ratio" in summary
    assert "verdict" in summary
    assert summary["verdict"] in ("PASS", "CAUTION", "FAIL")


@pytest.mark.asyncio
async def test_walk_forward_custom_step():
    """Walk-forward with custom step size (overlapping windows)."""
    rows = _make_ohlcv_rows(500)
    pool = MockPool(rows)

    result = await run_walk_forward(
        stock_code="005930",
        train_days=100,
        test_days=50,
        step_days=25,  # 50% overlap
        pool=pool,
    )

    # With step=25, we get more windows than with step=50
    assert result["total_windows"] >= 4


@pytest.mark.asyncio
async def test_walk_forward_mean_reversion_strategy():
    """Walk-forward works with mean_reversion strategy."""
    rows = _make_ohlcv_rows(400)
    pool = MockPool(rows)

    result = await run_walk_forward(
        stock_code="005930",
        strategy="mean_reversion",
        train_days=100,
        test_days=50,
        pool=pool,
    )

    assert result["strategy"] == "mean_reversion"
    assert result["total_windows"] >= 1


def test_walk_forward_result_verdict():
    """Test verdict calculation logic."""
    # PASS case
    good_windows = [
        WalkForwardWindow(
            window_id=i, train_start="", train_end="", test_start="", test_end="",
            train_bars=252, test_bars=63,
            oos_return=3.0, oos_max_drawdown=-5.0, oos_sharpe=0.8,
            oos_win_rate=55.0, oos_trades=10, oos_profit_factor=1.5,
        )
        for i in range(5)
    ]
    result = WalkForwardResult("005930", "ensemble", 10_000_000, good_windows, 1000)
    assert result.verdict == "PASS"
    assert result.consistency_ratio == 1.0

    # FAIL case — negative returns
    bad_windows = [
        WalkForwardWindow(
            window_id=i, train_start="", train_end="", test_start="", test_end="",
            train_bars=252, test_bars=63,
            oos_return=-5.0, oos_max_drawdown=-15.0, oos_sharpe=-0.5,
            oos_win_rate=30.0, oos_trades=5, oos_profit_factor=0.5,
        )
        for i in range(5)
    ]
    result_bad = WalkForwardResult("005930", "ensemble", 10_000_000, bad_windows, 1000)
    assert result_bad.verdict == "FAIL"

    # Empty windows
    result_empty = WalkForwardResult("005930", "ensemble", 10_000_000, [], 50)
    assert result_empty.verdict == "FAIL"


def test_walk_forward_result_compounded_return():
    """Test compounded return calculation."""
    windows = [
        WalkForwardWindow(
            window_id=0, train_start="", train_end="", test_start="", test_end="",
            train_bars=100, test_bars=50,
            oos_return=10.0, oos_max_drawdown=-3.0, oos_sharpe=1.0,
            oos_win_rate=60.0, oos_trades=5, oos_profit_factor=2.0,
        ),
        WalkForwardWindow(
            window_id=1, train_start="", train_end="", test_start="", test_end="",
            train_bars=100, test_bars=50,
            oos_return=5.0, oos_max_drawdown=-2.0, oos_sharpe=0.8,
            oos_win_rate=55.0, oos_trades=4, oos_profit_factor=1.5,
        ),
    ]
    result = WalkForwardResult("005930", "ensemble", 10_000_000, windows, 300)
    # 1.10 * 1.05 = 1.155 → 15.5%
    assert result.compounded_oos_return == 15.5
