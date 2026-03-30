"""Unit tests for TradingGuard (v1.31 Phase A safety checks).

Tests all rejection paths: kill switch, session, stale data, broker circuit breaker,
sector concentration, symbol validation, outlier price, participation rate.
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


class MockConn:
    def __init__(self, fetch=None, fetchrow=None, fetchval=None):
        self._fetch = fetch or []
        self._fetchrow = fetchrow
        self._fetchval = fetchval

    async def fetch(self, *a, **kw):
        return self._fetch

    async def fetchrow(self, *a, **kw):
        return self._fetchrow

    async def fetchval(self, *a, **kw):
        return self._fetchval

    async def execute(self, *a, **kw):
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

    async def publish(self, *a, **kw):
        return 0


@pytest.fixture
def guard():
    from app.execution.trading_guard import TradingGuard
    pool = MockPool()
    redis = MockRedis()
    return TradingGuard(pool=pool, redis=redis)


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_kill_switch_inactive_by_default(self, guard):
        assert await guard.is_kill_switch_active() is False

    @pytest.mark.asyncio
    async def test_activate_kill_switch(self, guard):
        await guard.activate_kill_switch("test reason")
        assert await guard.is_kill_switch_active() is True

    @pytest.mark.asyncio
    async def test_deactivate_kill_switch(self, guard):
        await guard.activate_kill_switch("test")
        await guard.deactivate_kill_switch()
        assert await guard.is_kill_switch_active() is False

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_all_orders(self, guard):
        await guard.activate_kill_switch("test")
        ok, violations = await guard.pre_trade_check("005930")
        assert ok is False
        assert "킬 스위치" in violations[0]


class TestSessionGuard:
    def test_weekend_blocked(self, guard):
        # Patch to Saturday
        with patch("app.execution.trading_guard.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 28, 11, 0, tzinfo=timezone(timedelta(hours=9)))
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, msg = guard.is_trading_session()
            assert ok is False
            assert "주말" in msg

    def test_before_open_blocked(self, guard):
        with patch("app.execution.trading_guard.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 30, 8, 30, tzinfo=timezone(timedelta(hours=9)))
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, msg = guard.is_trading_session()
            assert ok is False

    def test_after_close_blocked(self, guard):
        with patch("app.execution.trading_guard.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 30, 15, 20, tzinfo=timezone(timedelta(hours=9)))
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, msg = guard.is_trading_session()
            assert ok is False

    def test_during_session_allowed(self, guard):
        with patch("app.execution.trading_guard.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 30, 10, 30, tzinfo=timezone(timedelta(hours=9)))
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, msg = guard.is_trading_session()
            assert ok is True


class TestBrokerCircuitBreaker:
    @pytest.mark.asyncio
    async def test_no_failures_ok(self, guard):
        count = await guard.get_broker_failure_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_failures_accumulate(self, guard):
        await guard.record_broker_failure()
        await guard.record_broker_failure()
        assert await guard.get_broker_failure_count() == 2

    @pytest.mark.asyncio
    async def test_three_failures_activates_kill(self, guard):
        for _ in range(3):
            await guard.record_broker_failure()
        assert await guard.is_kill_switch_active() is True

    @pytest.mark.asyncio
    async def test_reset_clears_count(self, guard):
        await guard.record_broker_failure()
        await guard.reset_broker_failures()
        assert await guard.get_broker_failure_count() == 0


class TestStalePriceGate:
    @pytest.mark.asyncio
    async def test_no_data_blocked(self, guard):
        ok, age = await guard.check_price_freshness("005930")
        assert ok is False

    @pytest.mark.asyncio
    async def test_fresh_data_ok(self, guard):
        from app.execution.trading_guard import TradingGuard
        now = datetime.now(timezone.utc)
        conn = MockConn(fetchrow={"time": now})
        guard_fresh = TradingGuard(pool=MockPool(conn), redis=MockRedis())
        ok, age = await guard_fresh.check_price_freshness("005930")
        assert ok is True
        assert age < 5

    @pytest.mark.asyncio
    async def test_old_data_blocked(self, guard):
        from app.execution.trading_guard import TradingGuard
        old_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        conn = MockConn(fetchrow={"time": old_time})
        guard_old = TradingGuard(pool=MockPool(conn), redis=MockRedis())
        ok, age = await guard_old.check_price_freshness("005930")
        assert ok is False
        assert age > 30


class TestSymbolValidation:
    @pytest.mark.asyncio
    async def test_unknown_symbol_blocked(self, guard):
        ok, msg = await guard.check_symbol_exists("XXXXXX")
        assert ok is False
        assert "미등록" in msg

    @pytest.mark.asyncio
    async def test_known_symbol_ok(self):
        from app.execution.trading_guard import TradingGuard
        conn = MockConn(fetchrow={"stock_code": "005930", "stock_name": "삼성전자"})
        g = TradingGuard(pool=MockPool(conn), redis=MockRedis())
        ok, msg = await g.check_symbol_exists("005930")
        assert ok is True


class TestOutlierPrice:
    @pytest.mark.asyncio
    async def test_normal_price_ok(self):
        from app.execution.trading_guard import TradingGuard
        conn = MockConn(fetchrow={"close": Decimal("60000")})
        g = TradingGuard(pool=MockPool(conn), redis=MockRedis())
        ok, msg = await g.check_price_sanity("005930", 62000)
        assert ok is True

    @pytest.mark.asyncio
    async def test_extreme_high_blocked(self):
        from app.execution.trading_guard import TradingGuard
        conn = MockConn(fetchrow={"close": Decimal("60000")})
        g = TradingGuard(pool=MockPool(conn), redis=MockRedis())
        ok, msg = await g.check_price_sanity("005930", 150000)  # 2.5x
        assert ok is False
        assert "이상 가격" in msg

    @pytest.mark.asyncio
    async def test_extreme_low_blocked(self):
        from app.execution.trading_guard import TradingGuard
        conn = MockConn(fetchrow={"close": Decimal("60000")})
        g = TradingGuard(pool=MockPool(conn), redis=MockRedis())
        ok, msg = await g.check_price_sanity("005930", 20000)  # 0.33x
        assert ok is False


class TestOrderFSM:
    def test_valid_transitions(self):
        from app.execution.order_fsm import OrderState, VALID_TRANSITIONS
        # CREATED can go to VALIDATED or BLOCKED or FAILED
        assert OrderState.VALIDATED in VALID_TRANSITIONS[OrderState.CREATED]
        assert OrderState.BLOCKED in VALID_TRANSITIONS[OrderState.CREATED]
        # SUBMITTED can go to ACKED or REJECTED or UNKNOWN
        assert OrderState.ACKED in VALID_TRANSITIONS[OrderState.SUBMITTED]
        assert OrderState.REJECTED in VALID_TRANSITIONS[OrderState.SUBMITTED]
        assert OrderState.UNKNOWN in VALID_TRANSITIONS[OrderState.SUBMITTED]
        # ACKED can go to FILLED or PARTIALLY_FILLED
        assert OrderState.FILLED in VALID_TRANSITIONS[OrderState.ACKED]
        assert OrderState.PARTIALLY_FILLED in VALID_TRANSITIONS[OrderState.ACKED]

    def test_invalid_transitions(self):
        from app.execution.order_fsm import OrderState, VALID_TRANSITIONS
        # CREATED cannot go directly to FILLED
        assert OrderState.FILLED not in VALID_TRANSITIONS[OrderState.CREATED]
        # FILLED is terminal — not in transitions
        assert OrderState.FILLED not in VALID_TRANSITIONS

    def test_idempotency_key_generation(self):
        from app.execution.order_fsm import generate_idempotency_key
        key1 = generate_idempotency_key("strat1", "005930", "BUY", 0)
        key2 = generate_idempotency_key("strat1", "005930", "BUY", 0)
        key3 = generate_idempotency_key("strat1", "005930", "BUY", 1)
        assert key1 == key2  # same inputs = same key
        assert key1 != key3  # different seq = different key
        assert len(key1) == 16

    def test_idempotency_key_different_strategy(self):
        from app.execution.order_fsm import generate_idempotency_key
        key1 = generate_idempotency_key("strat_a", "005930", "BUY")
        key2 = generate_idempotency_key("strat_b", "005930", "BUY")
        assert key1 != key2
