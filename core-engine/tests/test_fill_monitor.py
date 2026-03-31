"""Tests for fill monitor and order cleanup."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.execution.fill_monitor import (
    check_inflight_orders,
    STALE_ORDER_MINUTES,
    AUTO_CANCEL_MINUTES,
)
from app.execution.order_cleanup import (
    cleanup_eod_orders,
    get_daily_order_summary,
)


class MockConn:
    def __init__(self, fetch_results=None, fetchrow_result=None):
        self._fetch_results = fetch_results or []
        self._fetchrow_result = fetchrow_result
        self.executed = []

    async def fetch(self, query, *args):
        return self._fetch_results

    async def fetchrow(self, query, *args):
        return self._fetchrow_result

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1"

    def transaction(self):
        return MockTransaction()


class MockTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


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


@pytest.mark.asyncio
async def test_check_inflight_no_orders():
    """No in-flight orders → empty result."""
    pool = MockPool(MockConn(fetch_results=[]))
    redis = AsyncMock()
    kis = MagicMock()

    result = await check_inflight_orders(pool=pool, redis=redis, kis_client=kis)

    assert result["checked"] == 0
    assert result["updated"] == 0


@pytest.mark.asyncio
async def test_check_inflight_stale_detection():
    """Stale orders are detected and counted."""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=STALE_ORDER_MINUTES + 1)
    orders = [
        {
            "order_id": "ORD-001",
            "stock_code": "005930",
            "side": "BUY",
            "quantity": 10,
            "price": 70000,
            "status": "ACKED",
            "time": old_time,
            "metadata_str": "{}",
        }
    ]
    pool = MockPool(MockConn(fetch_results=orders))
    redis = AsyncMock()
    kis = MagicMock()
    kis._request_with_retry = AsyncMock(return_value={"output1": []})

    with patch("app.execution.fill_monitor.settings") as mock_settings:
        mock_settings.kis_app_key = ""
        mock_settings.kis_base_url = "https://openapivts.koreainvestment.com:29443"
        result = await check_inflight_orders(pool=pool, redis=redis, kis_client=kis)

    assert result["checked"] == 1
    assert result["stale_alerts"] == 1


@pytest.mark.asyncio
async def test_check_inflight_auto_cancel():
    """Very old orders are auto-cancelled."""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=AUTO_CANCEL_MINUTES + 1)
    orders = [
        {
            "order_id": "ORD-OLD",
            "stock_code": "005930",
            "side": "BUY",
            "quantity": 10,
            "price": 70000,
            "status": "SUBMITTED",
            "time": old_time,
            "metadata_str": "{}",
        }
    ]
    pool = MockPool(MockConn(fetch_results=orders))
    redis = AsyncMock()
    kis = MagicMock()

    with patch("app.execution.fill_monitor.transition_order_state", new_callable=AsyncMock) as mock_trans, \
         patch("app.execution.fill_monitor.log_event", new_callable=AsyncMock):
        result = await check_inflight_orders(pool=pool, redis=redis, kis_client=kis)

    assert result["cancelled"] == 1
    mock_trans.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_eod_submitted_orders():
    """SUBMITTED orders are expired at EOD."""
    orders = [
        {
            "order_id": "ORD-SUB",
            "stock_code": "005930",
            "side": "BUY",
            "quantity": 10,
            "filled_qty": 0,
            "status": "SUBMITTED",
            "time": datetime.now(timezone.utc),
        }
    ]
    pool = MockPool(MockConn(fetch_results=orders))

    with patch("app.execution.order_cleanup.transition_order_state", new_callable=AsyncMock) as mock_trans, \
         patch("app.execution.order_cleanup.log_event", new_callable=AsyncMock):
        result = await cleanup_eod_orders(pool=pool)

    assert result["expired"] == 1
    mock_trans.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_eod_partial_fill():
    """PARTIALLY_FILLED orders are kept at EOD."""
    orders = [
        {
            "order_id": "ORD-PART",
            "stock_code": "005930",
            "side": "BUY",
            "quantity": 10,
            "filled_qty": 5,
            "status": "PARTIALLY_FILLED",
            "time": datetime.now(timezone.utc),
        }
    ]
    pool = MockPool(MockConn(fetch_results=orders))

    with patch("app.execution.order_cleanup.log_event", new_callable=AsyncMock):
        result = await cleanup_eod_orders(pool=pool)

    assert result["partial_kept"] == 1
    assert result["expired"] == 0


@pytest.mark.asyncio
async def test_cleanup_eod_unknown_orders():
    """UNKNOWN orders are flagged for review."""
    orders = [
        {
            "order_id": "ORD-UNK",
            "stock_code": "005930",
            "side": "BUY",
            "quantity": 10,
            "filled_qty": 0,
            "status": "UNKNOWN",
            "time": datetime.now(timezone.utc),
        }
    ]
    pool = MockPool(MockConn(fetch_results=orders))

    with patch("app.execution.order_cleanup.log_event", new_callable=AsyncMock):
        result = await cleanup_eod_orders(pool=pool)

    assert result["unknown_flagged"] == 1


@pytest.mark.asyncio
async def test_daily_order_summary():
    """Daily summary returns correct structure."""
    summary_row = {
        "total_orders": 15,
        "filled": 10,
        "partial": 2,
        "cancelled": 1,
        "rejected": 0,
        "expired": 1,
        "blocked": 1,
        "failed": 0,
        "buy_fills": 6,
        "sell_fills": 4,
    }
    quality_row = {
        "fills": 10,
        "avg_slippage": 3.5,
        "avg_delay": 12.3,
    }

    conn = MockConn()
    call_count = [0]
    orig_fetchrow = conn.fetchrow

    async def mock_fetchrow(query, *args):
        call_count[0] += 1
        if call_count[0] == 1:
            return summary_row
        return quality_row

    conn.fetchrow = mock_fetchrow
    pool = MockPool(conn)

    result = await get_daily_order_summary(pool=pool)

    assert result["total_orders"] == 15
    assert result["filled"] == 10
    assert result["fill_rate_pct"] == 80.0  # (10+2)/15
    assert result["execution_quality"]["avg_slippage_bps"] == 3.5


@pytest.mark.asyncio
async def test_cleanup_eod_no_orders():
    """No unresolved orders → clean result."""
    pool = MockPool(MockConn(fetch_results=[]))

    result = await cleanup_eod_orders(pool=pool)

    assert result["expired"] == 0
    assert result["partial_kept"] == 0
    assert result["unknown_flagged"] == 0
    assert result["errors"] == []
