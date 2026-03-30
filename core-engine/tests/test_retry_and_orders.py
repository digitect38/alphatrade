"""Tests for retry utility and order_manager execute_order flow."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx


# === Retry Utility ===


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        from app.utils.retry import retry_async
        func = AsyncMock(return_value="ok")
        result = await retry_async(func, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_connect_error(self):
        from app.utils.retry import retry_async
        func = AsyncMock(side_effect=[httpx.ConnectError("fail"), httpx.ConnectError("fail"), "ok"])
        result = await retry_async(func, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        from app.utils.retry import retry_async
        func = AsyncMock(side_effect=[httpx.ReadTimeout("timeout"), "ok"])
        result = await retry_async(func, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert func.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries(self):
        from app.utils.retry import retry_async
        func = AsyncMock(side_effect=httpx.ConnectError("always fail"))
        with pytest.raises(httpx.ConnectError):
            await retry_async(func, max_retries=2, base_delay=0.01)
        assert func.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_error_not_retried(self):
        from app.utils.retry import retry_async
        func = AsyncMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError):
            await retry_async(func, max_retries=3, base_delay=0.01)
        assert func.call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_decorator(self):
        from app.utils.retry import with_retry

        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectTimeout("timeout")
            return "done"

        result = await flaky()
        assert result == "done"
        assert call_count == 3


# === OrderManager execute_order ===


class MockConn:
    def __init__(self):
        self._fetchrow = None
        self._fetchval = None  # None = not found (for idempotency check)

    async def fetch(self, *a, **kw):
        return []

    async def fetchrow(self, *a, **kw):
        return self._fetchrow

    async def fetchval(self, *a, **kw):
        return self._fetchval

    async def execute(self, *a, **kw):
        return "INSERT 0 1"

    def transaction(self):
        return MockTx()


class MockTx:
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
    def __init__(self):
        self._store = {}

    async def publish(self, *a, **kw):
        return 0

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)

    async def incr(self, key):
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])

    async def expire(self, *a, **kw):
        pass


class TestExecuteOrder:
    """Tests for execute_order with TradingGuard bypassed (allows testing in any session)."""

    @pytest.fixture(autouse=True)
    def _bypass_guard(self):
        from unittest.mock import patch, AsyncMock as AM
        with patch("app.execution.trading_guard.TradingGuard") as MockGuard:
            g = MockGuard.return_value
            g.pre_trade_check = AM(return_value=(True, []))
            g.reset_broker_failures = AM()
            g.record_broker_failure = AM()
            yield

    def _make_deps(self, risk_allowed=True, broker_success=True):
        from app.execution.broker import BrokerClient, BrokerResponse
        from app.execution.risk_manager import RiskManager
        from app.models.execution import RiskCheckResult

        risk = MagicMock(spec=RiskManager)
        risk.check_order = AsyncMock(return_value=RiskCheckResult(
            allowed=risk_allowed,
            violations=["test violation"] if not risk_allowed else [],
            warnings=[],
        ))
        broker = MagicMock(spec=BrokerClient)
        broker.submit_order = AsyncMock(return_value=BrokerResponse(
            success=broker_success,
            filled_qty=10 if broker_success else 0,
            filled_price=60000 if broker_success else None,
            message="ok" if broker_success else "failed",
        ))
        return broker, risk

    @pytest.mark.asyncio
    async def test_execute_order_success(self):
        from app.execution.order_manager import execute_order
        from app.models.execution import OrderRequest

        broker, risk = self._make_deps(risk_allowed=True, broker_success=True)
        pool = MockPool()
        redis = MockRedis()
        redis._store = {}

        result = await execute_order(
            OrderRequest(stock_code="005930", side="BUY", quantity=10),
            pool=pool, redis=redis, broker=broker, risk_mgr=risk,
        )
        assert result.status == "FILLED"
        assert result.filled_qty == 10
        assert result.filled_price == 60000

    @pytest.mark.asyncio
    async def test_execute_order_risk_rejected(self):
        from app.execution.order_manager import execute_order
        from app.models.execution import OrderRequest

        broker, risk = self._make_deps(risk_allowed=False)
        pool = MockPool()
        redis = MockRedis()

        result = await execute_order(
            OrderRequest(stock_code="005930", side="BUY", quantity=10),
            pool=pool, redis=redis, broker=broker, risk_mgr=risk,
        )
        assert result.status == "FAILED"
        assert "리스크 체크 실패" in result.message

    @pytest.mark.asyncio
    async def test_execute_order_broker_failed(self):
        from app.execution.order_manager import execute_order
        from app.models.execution import OrderRequest

        broker, risk = self._make_deps(risk_allowed=True, broker_success=False)
        pool = MockPool()
        redis = MockRedis()

        result = await execute_order(
            OrderRequest(stock_code="005930", side="SELL", quantity=5),
            pool=pool, redis=redis, broker=broker, risk_mgr=risk,
        )
        assert result.status == "FAILED"
        assert result.message == "failed"

    @pytest.mark.asyncio
    async def test_get_portfolio_state_with_snapshot(self):
        from app.execution.order_manager import _get_portfolio_state
        conn = MockConn()
        conn._fetchrow = {"total_value": Decimal("10500000"), "cash": Decimal("9000000")}
        pool = MockPool(conn)

        pv, cash = await _get_portfolio_state(pool=pool)
        assert pv == 10500000
        assert cash == 9000000

    @pytest.mark.asyncio
    async def test_get_portfolio_state_no_snapshot(self):
        from app.execution.order_manager import _get_portfolio_state
        pool = MockPool()

        pv, cash = await _get_portfolio_state(pool=pool)
        from app.config import settings
        assert pv == settings.initial_capital
        assert cash == settings.initial_capital
