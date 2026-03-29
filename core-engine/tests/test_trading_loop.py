"""Tests for trading loop, monitor, and scanner with all dependencies mocked."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import *


# Shared mock infrastructure

class MockConn:
    def __init__(self, fetch_data=None, fetchrow_data=None, fetchval_data=None):
        self._fetch = fetch_data or []
        self._fetchrow = fetchrow_data
        self._fetchval = fetchval_data or 0

    async def fetch(self, *a, **kw):
        return self._fetch

    async def fetchrow(self, *a, **kw):
        return self._fetchrow

    async def fetchval(self, *a, **kw):
        return self._fetchval

    async def execute(self, *a, **kw):
        return "INSERT 0 1"

    def transaction(self):
        return MockTransaction()


class MockTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockPool:
    def __init__(self, conn=None):
        self.conn = conn or MockConn()

    def acquire(self):
        return MockAcquire(self.conn)


class MockAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class MockRedis:
    async def publish(self, *a, **kw):
        return 0

    async def get(self, *a, **kw):
        return None

    async def setex(self, *a, **kw):
        pass


def _make_services():
    from app.services.kis_api import KISClient
    from app.services.naver_news import NaverNewsClient
    from app.services.notification import NotificationService
    from app.execution.broker import BrokerClient, BrokerResponse
    from app.execution.risk_manager import RiskManager
    from app.models.execution import RiskCheckResult

    kis = MagicMock(spec=KISClient)
    kis.get_current_price = AsyncMock(return_value=None)
    naver = MagicMock(spec=NaverNewsClient)
    naver.fetch_rss_news = AsyncMock(return_value=[])
    notifier = MagicMock(spec=NotificationService)
    notifier.alert_stop_loss = AsyncMock()
    notifier.alert_take_profit = AsyncMock()
    notifier.alert_price_surge = AsyncMock()
    broker = MagicMock(spec=BrokerClient)
    broker.submit_order = AsyncMock(return_value=BrokerResponse(success=True, filled_qty=10, filled_price=60000))
    risk = MagicMock(spec=RiskManager)
    risk.check_order = AsyncMock(return_value=RiskCheckResult(allowed=True))
    risk.check_stop_loss = AsyncMock(return_value=False)
    risk.check_take_profit = AsyncMock(return_value=False)

    return kis, naver, notifier, broker, risk


# === Trading Loop ===


class TestTradingLoop:
    @pytest.mark.asyncio
    async def test_save_portfolio_snapshot_empty(self):
        from app.trading.loop import save_portfolio_snapshot
        pool = MockPool(MockConn(fetch_data=[], fetchrow_data=None))
        result = await save_portfolio_snapshot(pool=pool)
        assert "total_value" in result
        assert result["positions"] == 0

    @pytest.mark.asyncio
    async def test_save_portfolio_snapshot_with_positions(self):
        from app.trading.loop import save_portfolio_snapshot
        positions = [
            {"stock_code": "005930", "quantity": 10, "avg_price": Decimal("60000"), "current_price": Decimal("62000")},
        ]
        snapshot = {"total_value": Decimal("10000000"), "cash": Decimal("9400000")}

        call_count = 0
        async def mock_fetch(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return positions
            return []  # history

        async def mock_fetchrow(*a, **kw):
            return snapshot

        conn = MockConn()
        conn.fetch = mock_fetch
        conn.fetchrow = mock_fetchrow
        pool = MockPool(conn)

        result = await save_portfolio_snapshot(pool=pool)
        assert result["positions"] == 1
        assert result["total_value"] > 0

    @pytest.mark.asyncio
    async def test_run_trading_cycle_empty_universe(self):
        from app.trading.loop import run_trading_cycle
        kis, naver, notifier, broker, risk = _make_services()
        pool = MockPool()
        redis = MockRedis()

        result = await run_trading_cycle(
            pool=pool, redis=redis, kis_client=kis, naver_client=naver,
            broker=broker, risk_mgr=risk, notifier=notifier,
        )
        assert "started_at" in result
        assert "steps" in result
        assert result["status"] in ("success", "partial")


# === Monitor ===


class TestMonitor:
    @pytest.mark.asyncio
    async def test_check_positions_empty(self):
        from app.trading.monitor import check_positions
        _, _, notifier, broker, risk = _make_services()
        pool = MockPool()
        redis = MockRedis()

        result = await check_positions(pool=pool, redis=redis, broker=broker, risk_mgr=risk, notifier=notifier)
        assert result["positions_checked"] == 0
        assert result["stop_loss_triggered"] == []

    @pytest.mark.asyncio
    async def test_check_positions_with_stop_loss(self):
        from app.trading.monitor import check_positions
        kis, _, notifier, broker, risk = _make_services()
        risk.check_stop_loss = AsyncMock(return_value=True)
        risk.check_take_profit = AsyncMock(return_value=False)

        from app.execution.broker import BrokerResponse
        broker.submit_order = AsyncMock(return_value=BrokerResponse(success=True, filled_qty=10, filled_price=58000))
        risk.check_order = AsyncMock(return_value=MagicMock(allowed=True, violations=[], warnings=[]))

        positions = [
            {"stock_code": "005930", "quantity": 10, "avg_price": Decimal("60000"), "current_price": Decimal("57000")},
        ]
        pool = MockPool(MockConn(fetch_data=positions))
        redis = MockRedis()

        result = await check_positions(pool=pool, redis=redis, broker=broker, risk_mgr=risk, notifier=notifier)
        assert result["positions_checked"] == 1
        assert len(result["stop_loss_triggered"]) == 1

    @pytest.mark.asyncio
    async def test_check_positions_with_take_profit(self):
        from app.trading.monitor import check_positions
        _, _, notifier, broker, risk = _make_services()
        risk.check_stop_loss = AsyncMock(return_value=False)
        risk.check_take_profit = AsyncMock(return_value=True)

        from app.execution.broker import BrokerResponse
        broker.submit_order = AsyncMock(return_value=BrokerResponse(success=True, filled_qty=10, filled_price=66000))
        risk.check_order = AsyncMock(return_value=MagicMock(allowed=True, violations=[], warnings=[]))

        positions = [
            {"stock_code": "005930", "quantity": 10, "avg_price": Decimal("60000"), "current_price": Decimal("66000")},
        ]
        pool = MockPool(MockConn(fetch_data=positions))
        redis = MockRedis()

        result = await check_positions(pool=pool, redis=redis, broker=broker, risk_mgr=risk, notifier=notifier)
        assert len(result["take_profit_triggered"]) == 1


# === Scanner ===


class TestMorningScanner:
    @pytest.mark.asyncio
    async def test_run_morning_scan_empty_universe(self):
        from app.scanner.morning import run_morning_scan
        kis, _, notifier, broker, risk = _make_services()
        pool = MockPool()
        redis = MockRedis()

        result = await run_morning_scan(
            pool=pool, redis=redis, kis_client=kis, broker=broker, risk_mgr=risk, notifier=notifier,
        )
        assert result["status"] == "empty"

    @pytest.mark.asyncio
    async def test_run_morning_scan_no_prices(self):
        from app.scanner.morning import run_morning_scan
        kis, _, notifier, broker, risk = _make_services()
        kis.get_current_price = AsyncMock(return_value=None)

        universe = [{"stock_code": "005930", "stock_name": "삼성전자"}]
        pool = MockPool(MockConn(fetch_data=universe))
        redis = MockRedis()

        result = await run_morning_scan(
            pool=pool, redis=redis, kis_client=kis, broker=broker, risk_mgr=risk, notifier=notifier,
        )
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_calc_momentum_score(self):
        from app.scanner.morning import _calc_momentum_score
        score = _calc_momentum_score(0.05, 3.0)
        assert score > 0
        score_neg = _calc_momentum_score(-0.03, 1.0)
        assert score_neg < 0
