"""Runtime-oriented tests for order FSM behavior."""

from unittest.mock import AsyncMock, patch

import pytest


class FSMConn:
    def __init__(self, initial_status="CREATED", inflight_rows=None):
        self.status = initial_status
        self.inflight_rows = inflight_rows or []
        self.executed = []

    async def fetchrow(self, query, *args):
        if "SELECT status FROM orders" in query:
            return {"status": self.status}
        return None

    async def fetch(self, query, *args):
        if "WHERE status IN ('SUBMITTED', 'ACKED', 'PARTIALLY_FILLED', 'UNKNOWN')" in query:
            return self.inflight_rows
        return []

    async def execute(self, query, *args):
        if "UPDATE orders SET status" in query:
            self.status = args[0]
        self.executed.append((query, args))
        return "UPDATE 1"


class FSMAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class FSMPool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FSMAcquire(self.conn)


class TestOrderFSMRuntime:
    @pytest.mark.asyncio
    async def test_transition_order_state_valid(self):
        from app.execution.order_fsm import OrderState, transition_order_state

        conn = FSMConn(initial_status="CREATED")
        pool = FSMPool(conn)

        with patch("app.execution.order_fsm.log_event", new=AsyncMock()) as mock_log:
            ok = await transition_order_state(pool, "ORD-1", OrderState.VALIDATED, "risk passed")

        assert ok is True
        assert conn.status == "VALIDATED"
        mock_log.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transition_order_state_invalid(self):
        from app.execution.order_fsm import OrderState, transition_order_state

        conn = FSMConn(initial_status="CREATED")
        pool = FSMPool(conn)

        with patch("app.execution.order_fsm.log_event", new=AsyncMock()) as mock_log:
            ok = await transition_order_state(pool, "ORD-1", OrderState.FILLED, "invalid jump")

        assert ok is False
        assert conn.status == "CREATED"
        mock_log.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recover_inflight_orders_returns_transitional_orders(self):
        from app.execution.order_fsm import recover_inflight_orders

        inflight = [
            {"order_id": "ORD-1", "stock_code": "005930", "side": "BUY", "quantity": 10, "filled_qty": 0, "status": "SUBMITTED", "metadata": {}},
            {"order_id": "ORD-2", "stock_code": "000660", "side": "SELL", "quantity": 5, "filled_qty": 2, "status": "PARTIALLY_FILLED", "metadata": {}},
        ]
        conn = FSMConn(inflight_rows=inflight)
        pool = FSMPool(conn)

        with patch("app.execution.order_fsm.log_event", new=AsyncMock()) as mock_log:
            result = await recover_inflight_orders(pool)

        assert len(result) == 2
        assert result[0]["order_id"] == "ORD-1"
        assert result[1]["status"] == "PARTIALLY_FILLED"
        mock_log.assert_awaited_once()

