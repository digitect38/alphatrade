"""Order Finite State Machine per v1.31 Section 16.5.2.

States: created → validated → submitted → acked → partially_filled →
        filled / cancelled / rejected / expired / unknown

Features:
- Idempotency key: strategy_id + trading_day + symbol + side + intent_seq
- Submit timeout: 3 seconds → unknown → broker query
- Partial fill handling with risk recalculation
- Restart recovery for in-flight orders
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from enum import Enum

import asyncpg

from app.services.audit import log_event
from app.utils.market_calendar import KST

logger = logging.getLogger(__name__)


class OrderState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


# Valid state transitions
VALID_TRANSITIONS = {
    OrderState.CREATED: {OrderState.VALIDATED, OrderState.BLOCKED, OrderState.FAILED},
    OrderState.VALIDATED: {OrderState.SUBMITTED, OrderState.FAILED},
    OrderState.SUBMITTED: {OrderState.ACKED, OrderState.REJECTED, OrderState.UNKNOWN, OrderState.FAILED},
    OrderState.ACKED: {OrderState.FILLED, OrderState.PARTIALLY_FILLED, OrderState.CANCELLED, OrderState.EXPIRED},
    OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCELLED, OrderState.EXPIRED},
    OrderState.UNKNOWN: {OrderState.ACKED, OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELLED, OrderState.EXPIRED},
}


def generate_idempotency_key(
    strategy_id: str | None,
    symbol: str,
    side: str,
    intent_seq: int = 0,
) -> str:
    """Generate idempotency key per v1.31 spec.

    Format: SHA-256(strategy_id + trading_day + symbol + side + intent_seq)
    """
    trading_day = datetime.now(KST).strftime("%Y%m%d")
    raw = f"{strategy_id or 'manual'}:{trading_day}:{symbol}:{side}:{intent_seq}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def check_duplicate_order(
    pool: asyncpg.Pool,
    idempotency_key: str,
) -> bool:
    """Check if an order with this idempotency key already exists today."""
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE metadata->>'idempotency_key' = $1
              AND time > CURRENT_DATE
            LIMIT 1
            """,
            idempotency_key,
        )
    return exists is not None


async def transition_order_state(
    pool: asyncpg.Pool,
    order_id: str,
    new_state: OrderState,
    message: str = "",
) -> bool:
    """Transition an order to a new state with validation.

    Returns True if transition was valid, False if rejected.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM orders WHERE order_id = $1 ORDER BY time DESC LIMIT 1",
            order_id,
        )
        if not row:
            logger.error("Order %s not found for state transition", order_id)
            return False

        current = OrderState(row["status"])
        valid_next = VALID_TRANSITIONS.get(current, set())

        if new_state not in valid_next:
            logger.warning(
                "Invalid order transition: %s → %s (order=%s)",
                current.value, new_state.value, order_id,
            )
            return False

        await conn.execute(
            "UPDATE orders SET status = $1, metadata = metadata || $2::jsonb WHERE order_id = $3 AND time > CURRENT_DATE - INTERVAL '1 day'",
            new_state.value,
            f'{{"state_change": "{current.value}->{new_state.value}", "change_reason": "{message}"}}',
            order_id,
        )

    await log_event(
        pool, source="order_fsm", event_type="state_transition",
        correlation_id=order_id,
        payload={"from": current.value, "to": new_state.value, "reason": message},
    )

    logger.info("Order %s: %s → %s (%s)", order_id, current.value, new_state.value, message)
    return True


async def recover_inflight_orders(pool: asyncpg.Pool) -> list[dict]:
    """Recover orders in transitional states after process restart.

    Per v1.31: submitted/acked/partially_filled/unknown orders
    need broker state verification on startup.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_id, stock_code, side, quantity, filled_qty, status, metadata
            FROM orders
            WHERE status IN ('SUBMITTED', 'ACKED', 'PARTIALLY_FILLED', 'UNKNOWN')
              AND time > CURRENT_DATE - INTERVAL '1 day'
            ORDER BY time ASC
            """,
        )

    inflight = []
    for row in rows:
        inflight.append({
            "order_id": row["order_id"],
            "stock_code": row["stock_code"],
            "side": row["side"],
            "quantity": row["quantity"],
            "filled_qty": row["filled_qty"],
            "status": row["status"],
        })
        logger.warning("Inflight order found: %s status=%s", row["order_id"], row["status"])

    if inflight:
        await log_event(
            pool, source="order_fsm", event_type="restart_recovery",
            payload={"inflight_count": len(inflight), "orders": [o["order_id"] for o in inflight]},
        )

    return inflight
