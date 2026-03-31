"""Tests for risk module: real-time P&L, VaR, stress test, alert escalation."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.risk.realtime_pnl import compute_realtime_pnl
from app.risk.stress_test import run_stress_test, STRESS_SCENARIOS, _apply_scenario
from app.services.alert_escalation import AlertEscalation, AlertLevel, EVENT_LEVELS


# === Mock helpers ===

class MockConn:
    def __init__(self, fetch_data=None, fetchrow_data=None):
        self._fetch = fetch_data or []
        self._fetchrow = fetchrow_data
        self._call_idx = 0

    async def fetch(self, query, *args):
        if isinstance(self._fetch, list) and self._fetch and isinstance(self._fetch[0], list):
            # Multiple call support
            idx = min(self._call_idx, len(self._fetch) - 1)
            self._call_idx += 1
            return self._fetch[idx]
        return self._fetch

    async def fetchrow(self, query, *args):
        return self._fetchrow

    async def fetchval(self, query, *args):
        return 0


class MockPool:
    def __init__(self, conn=None):
        self._conn = conn or MockConn()

    def acquire(self):
        return MockAcquire(self._conn)


class MockAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockRedis:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def exists(self, key):
        return key in self._store

    async def ttl(self, key):
        return 60

    def scan_iter(self, match="*"):
        return MockScanIter(self._store, match)


class MockScanIter:
    def __init__(self, store, match):
        prefix = match.replace("*", "")
        self._keys = [k for k in store if k.startswith(prefix)]
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._keys):
            raise StopAsyncIteration
        key = self._keys[self._idx]
        self._idx += 1
        return key


# === Real-time P&L tests ===

@pytest.mark.asyncio
async def test_realtime_pnl_no_positions():
    """Empty portfolio returns zeros."""
    conn = MockConn(
        fetch_data=[],
        fetchrow_data={"total_value": Decimal("10000000"), "cash": Decimal("10000000"), "daily_pnl": Decimal("0")},
    )
    pool = MockPool(conn)
    redis = MockRedis()

    result = await compute_realtime_pnl(pool=pool, redis=redis)

    assert result["positions_count"] == 0
    assert result["total_unrealized_pnl"] == 0
    assert result["cash"] == 10_000_000


@pytest.mark.asyncio
async def test_realtime_pnl_with_positions():
    """Portfolio with positions computes correct P&L."""
    positions = [
        {"stock_code": "005930", "quantity": 10, "avg_price": Decimal("70000"), "current_price": Decimal("75000")},
        {"stock_code": "000660", "quantity": 5, "avg_price": Decimal("120000"), "current_price": Decimal("110000")},
    ]
    snapshot = {"total_value": Decimal("2000000"), "cash": Decimal("500000"), "daily_pnl": Decimal("10000")}

    conn = MockConn(fetch_data=positions, fetchrow_data=snapshot)
    pool = MockPool(conn)
    redis = MockRedis()

    result = await compute_realtime_pnl(pool=pool, redis=redis)

    assert result["positions_count"] == 2
    # 005930: 10 * (75000-70000) = 50000 gain
    # 000660: 5 * (110000-120000) = -50000 loss
    assert result["total_unrealized_pnl"] == 0  # net zero


# === Stress Test tests ===

def test_stress_scenarios_defined():
    """All built-in scenarios exist and have required fields."""
    assert len(STRESS_SCENARIOS) >= 5
    for key, scenario in STRESS_SCENARIOS.items():
        assert "name" in scenario
        assert "description" in scenario
        assert "market_shock_pct" in scenario
        assert "duration_days" in scenario
        assert isinstance(scenario["market_shock_pct"], (int, float))


def test_apply_scenario_covid():
    """COVID scenario applies correct shocks."""
    positions = [
        {"stock_code": "005930", "stock_name": "Samsung", "sector": "반도체", "quantity": 10, "current_price": 70000, "current_value": 700000},
        {"stock_code": "003490", "stock_name": "Daehan", "sector": "항공", "quantity": 5, "current_price": 30000, "current_value": 150000},
    ]
    result = _apply_scenario(positions, 1_000_000, 150_000, "covid_crash", STRESS_SCENARIOS["covid_crash"])

    assert result["scenario_key"] == "covid_crash"
    assert result["portfolio_impact_pct"] < 0
    # 항공 gets -50% vs 반도체 -20%, so 항공 hit harder
    impacts = {p["stock_code"]: p["shock_pct"] for p in result["position_impacts"]}
    assert impacts["003490"] == -50.0
    assert impacts["005930"] == -20.0


def test_apply_scenario_circuit_breaker():
    """Circuit breaker applies uniform market shock."""
    positions = [
        {"stock_code": "005930", "stock_name": "Samsung", "sector": "반도체", "quantity": 10, "current_price": 70000, "current_value": 700000},
    ]
    result = _apply_scenario(positions, 1_000_000, 300_000, "circuit_breaker", STRESS_SCENARIOS["circuit_breaker"])

    assert result["market_shock_pct"] == -8.0
    # No sector-specific shocks, so all use market shock
    assert result["position_impacts"][0]["shock_pct"] == -8.0


@pytest.mark.asyncio
async def test_stress_test_no_positions():
    """Stress test with no positions returns message."""
    pool = MockPool(MockConn(fetch_data=[], fetchrow_data=None))
    result = await run_stress_test(pool=pool)
    assert "message" in result


@pytest.mark.asyncio
async def test_stress_test_with_positions():
    """Stress test with positions returns all scenarios."""
    positions = [
        {"stock_code": "005930", "quantity": 10, "avg_price": Decimal("70000"),
         "current_price": Decimal("75000"), "sector": "반도체", "stock_name": "Samsung"},
    ]
    snapshot = {"total_value": Decimal("1000000"), "cash": Decimal("250000")}

    conn = MockConn(fetch_data=positions, fetchrow_data=snapshot)
    pool = MockPool(conn)

    result = await run_stress_test(pool=pool)

    assert "scenarios" in result
    assert len(result["scenarios"]) == len(STRESS_SCENARIOS)
    assert result["worst_scenario"]["impact_pct"] < 0


# === Alert Escalation tests ===

def test_event_levels_coverage():
    """All event types have defined levels."""
    for event_type, level in EVENT_LEVELS.items():
        assert isinstance(level, AlertLevel)
    assert EVENT_LEVELS["kill_switch"] == AlertLevel.CRITICAL
    assert EVENT_LEVELS["signal_generated"] == AlertLevel.INFO
    assert EVENT_LEVELS["stop_loss"] == AlertLevel.WARN


@pytest.mark.asyncio
async def test_alert_escalation_info():
    """INFO level alert sends to telegram only."""
    notifier = MagicMock()
    notifier.send_telegram = AsyncMock(return_value=True)
    redis = MockRedis()

    escalation = AlertEscalation(notifier, redis)
    result = await escalation.send("signal_generated", "BUY signal for 005930")

    assert result["sent"] is True
    assert result["level"] == AlertLevel.INFO
    notifier.send_telegram.assert_called_once()


@pytest.mark.asyncio
async def test_alert_escalation_cooldown():
    """Same event within cooldown period is suppressed."""
    notifier = MagicMock()
    notifier.send_telegram = AsyncMock(return_value=True)
    redis = MockRedis()

    escalation = AlertEscalation(notifier, redis)

    # First send
    result1 = await escalation.send("signal_generated", "BUY signal")
    assert result1["sent"] is True

    # Second send within cooldown
    result2 = await escalation.send("signal_generated", "another signal")
    assert result2["sent"] is False
    assert result2["reason"] == "cooldown_active"


@pytest.mark.asyncio
async def test_alert_escalation_critical():
    """CRITICAL level sends double-tap."""
    notifier = MagicMock()
    notifier.send_telegram = AsyncMock(return_value=True)
    redis = MockRedis()

    escalation = AlertEscalation(notifier, redis)
    result = await escalation.send("kill_switch", "Kill switch activated!")

    assert result["level"] == AlertLevel.CRITICAL
    # Should send at least twice (main + repeat)
    assert notifier.send_telegram.call_count >= 2


@pytest.mark.asyncio
async def test_alert_escalation_force_bypass_cooldown():
    """Force flag bypasses cooldown."""
    notifier = MagicMock()
    notifier.send_telegram = AsyncMock(return_value=True)
    redis = MockRedis()

    escalation = AlertEscalation(notifier, redis)

    await escalation.send("signal_generated", "first")
    result = await escalation.send("signal_generated", "forced", force=True)
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_alert_stats():
    """Alert stats returns active cooldowns."""
    notifier = MagicMock()
    notifier.send_telegram = AsyncMock(return_value=True)
    redis = MockRedis()

    escalation = AlertEscalation(notifier, redis)
    await escalation.send("signal_generated", "test")

    stats = await escalation.get_alert_stats()
    assert stats["total_active"] >= 1
