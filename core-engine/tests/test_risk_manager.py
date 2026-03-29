"""Tests for risk manager logic (unit tests, no DB).

~150 test cases.
"""

import pytest
from app.execution.risk_manager import RiskManager


class TestRiskManagerConstants:
    rm = RiskManager()

    def test_max_total_capital(self):
        assert self.rm.MAX_TOTAL_CAPITAL == 500_000

    def test_max_per_stock(self):
        assert self.rm.MAX_PER_STOCK == 250_000

    def test_stop_loss(self):
        assert self.rm.STOP_LOSS_PCT == -0.03

    def test_take_profit(self):
        assert self.rm.TAKE_PROFIT_PCT == 0.10

    def test_max_daily_loss(self):
        assert self.rm.MAX_DAILY_LOSS_PCT == -0.02

    def test_max_daily_trades(self):
        assert self.rm.MAX_DAILY_TRADES == 10

    def test_max_position_ratio(self):
        assert self.rm.MAX_POSITION_RATIO == 0.20

    def test_max_total_invested(self):
        assert self.rm.MAX_TOTAL_INVESTED == 0.90


class TestStopLoss:
    rm = RiskManager()

    @pytest.mark.parametrize("avg,current,expected", [
        (60000, 57000, True),    # -5% → stop loss (-3% threshold)
        (60000, 58200, True),    # -3% exactly → triggers (uses <=)
        (60000, 58000, True),    # -3.33% → stop loss
        (60000, 59000, False),   # -1.67% → ok
        (60000, 60000, False),   # 0% → ok
        (60000, 65000, False),   # +8.33% → ok
        (100000, 96000, True),   # -4% → stop loss
        (100000, 97000, True),   # -3% → stop loss
        (100000, 98000, False),  # -2% → ok
    ])
    @pytest.mark.asyncio
    async def test_stop_loss_trigger(self, avg, current, expected):
        result = await self.rm.check_stop_loss("T", avg, current)
        assert result == expected

    @pytest.mark.asyncio
    async def test_zero_avg_price(self):
        assert await self.rm.check_stop_loss("T", 0, 50000) is False

    @pytest.mark.asyncio
    async def test_negative_avg_price(self):
        assert await self.rm.check_stop_loss("T", -100, 50000) is False


class TestTakeProfit:
    rm = RiskManager()

    @pytest.mark.parametrize("avg,current,expected", [
        (60000, 66000, True),    # +10% → take profit
        (60000, 67000, True),    # +11.67% → take profit
        (60000, 65000, False),   # +8.33% → not yet
        (60000, 60000, False),   # 0% → no
        (60000, 55000, False),   # -8.33% → no
        (100000, 110000, True),  # +10% → take profit
        (100000, 109000, False), # +9% → not yet
    ])
    @pytest.mark.asyncio
    async def test_take_profit_trigger(self, avg, current, expected):
        result = await self.rm.check_take_profit("T", avg, current)
        assert result == expected

    @pytest.mark.asyncio
    async def test_zero_avg_price(self):
        assert await self.rm.check_take_profit("T", 0, 50000) is False


class TestStopLossTakeProfitBoundary:
    """Test boundary conditions between stop-loss and take-profit."""
    rm = RiskManager()

    @pytest.mark.parametrize("pnl_pct", [-0.10, -0.05, -0.03, -0.02, -0.01, 0.0,
                                          0.01, 0.05, 0.08, 0.10, 0.15, 0.20])
    @pytest.mark.asyncio
    async def test_pnl_boundaries(self, pnl_pct):
        avg = 100000
        current = avg * (1 + pnl_pct)
        sl = await self.rm.check_stop_loss("T", avg, current)
        tp = await self.rm.check_take_profit("T", avg, current)

        # Should never trigger both
        assert not (sl and tp)

        if pnl_pct <= -0.03:
            assert sl is True
        else:
            assert sl is False

        if pnl_pct >= 0.10:
            assert tp is True
        else:
            assert tp is False
