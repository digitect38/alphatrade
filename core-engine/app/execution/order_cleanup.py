"""Order cleanup — end-of-day housekeeping for unresolved orders.

Runs after market close to:
1. Cancel/expire all remaining in-flight orders
2. Handle partial fills (decide on remaining quantity)
3. Generate daily order summary
"""

import logging
from datetime import datetime, timezone

import asyncpg

from app.execution.order_fsm import OrderState, transition_order_state
from app.services.audit import log_event

logger = logging.getLogger(__name__)


async def cleanup_eod_orders(*, pool: asyncpg.Pool) -> dict:
    """Clean up all unresolved orders at end of day.

    Should be called after market close (15:40 KST or later).

    Actions:
    - SUBMITTED/ACKED orders → EXPIRED (assumed unfilled at close)
    - PARTIALLY_FILLED → keep as-is (already partially updated positions)
    - UNKNOWN → flag for manual review

    Returns summary dict.
    """
    now = datetime.now(timezone.utc)
    results = {
        "expired": 0,
        "partial_kept": 0,
        "unknown_flagged": 0,
        "errors": [],
    }

    async with pool.acquire() as conn:
        # Get all unresolved orders from today
        unresolved = await conn.fetch(
            """
            SELECT order_id, stock_code, side, quantity, filled_qty, status, time
            FROM orders
            WHERE status IN ('SUBMITTED', 'ACKED', 'PARTIALLY_FILLED', 'UNKNOWN')
              AND time > CURRENT_DATE - INTERVAL '1 day'
            ORDER BY time ASC
            """
        )

    for order in unresolved:
        order_id = order["order_id"]
        status = order["status"]

        try:
            if status in ("SUBMITTED", "ACKED"):
                # Never filled — mark expired
                await transition_order_state(
                    pool, order_id, OrderState.EXPIRED,
                    "EOD cleanup: order never filled before market close",
                )
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE orders SET status = 'EXPIRED' WHERE order_id = $1 AND time > CURRENT_DATE - INTERVAL '1 day'",
                        order_id,
                    )
                results["expired"] += 1

                await log_event(
                    pool, source="order_cleanup", event_type="eod_expired",
                    symbol=order["stock_code"], correlation_id=order_id,
                    payload={
                        "side": order["side"],
                        "quantity": order["quantity"],
                        "reason": "unfilled_at_close",
                    },
                )

            elif status == "PARTIALLY_FILLED":
                # Keep partial fill — position already updated for filled portion
                # Remaining quantity is abandoned
                filled = order["filled_qty"] or 0
                remaining = order["quantity"] - filled
                results["partial_kept"] += 1

                await log_event(
                    pool, source="order_cleanup", event_type="eod_partial_kept",
                    symbol=order["stock_code"], correlation_id=order_id,
                    payload={
                        "side": order["side"],
                        "total_qty": order["quantity"],
                        "filled_qty": filled,
                        "abandoned_qty": remaining,
                    },
                )
                logger.info(
                    "Partial fill kept: %s filled=%d/%d (abandoned %d)",
                    order_id, filled, order["quantity"], remaining,
                )

            elif status == "UNKNOWN":
                results["unknown_flagged"] += 1
                await log_event(
                    pool, source="order_cleanup", event_type="eod_unknown_flagged",
                    symbol=order["stock_code"], correlation_id=order_id,
                    payload={
                        "side": order["side"],
                        "quantity": order["quantity"],
                        "message": "requires manual review",
                    },
                )
                logger.warning("Unknown order flagged for review: %s", order_id)

        except Exception as e:
            results["errors"].append(f"{order_id}: {e}")
            logger.error("EOD cleanup error for %s: %s", order_id, e)

    total = results["expired"] + results["partial_kept"] + results["unknown_flagged"]
    logger.info(
        "EOD order cleanup: %d orders processed (expired=%d, partial=%d, unknown=%d)",
        total, results["expired"], results["partial_kept"], results["unknown_flagged"],
    )

    return results


async def get_daily_order_summary(*, pool: asyncpg.Pool) -> dict:
    """Generate daily order execution summary."""
    async with pool.acquire() as conn:
        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status = 'FILLED' THEN 1 END) as filled,
                COUNT(CASE WHEN status = 'PARTIALLY_FILLED' THEN 1 END) as partial,
                COUNT(CASE WHEN status = 'CANCELLED' THEN 1 END) as cancelled,
                COUNT(CASE WHEN status = 'REJECTED' THEN 1 END) as rejected,
                COUNT(CASE WHEN status = 'EXPIRED' THEN 1 END) as expired,
                COUNT(CASE WHEN status = 'BLOCKED' THEN 1 END) as blocked,
                COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed,
                COUNT(CASE WHEN side = 'BUY' AND status = 'FILLED' THEN 1 END) as buy_fills,
                COUNT(CASE WHEN side = 'SELL' AND status = 'FILLED' THEN 1 END) as sell_fills
            FROM orders
            WHERE time > CURRENT_DATE
            """
        )

        # Execution quality for today
        quality = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as fills,
                AVG(slippage_bps) as avg_slippage,
                AVG(fill_delay_seconds) as avg_delay
            FROM execution_quality
            WHERE time > CURRENT_DATE
            """
        )

    fill_rate = 0.0
    total = summary["total_orders"] if summary else 0
    if total > 0:
        filled = (summary["filled"] or 0) + (summary["partial"] or 0)
        fill_rate = round(filled / total * 100, 1)

    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_orders": total,
        "filled": summary["filled"] or 0,
        "partial": summary["partial"] or 0,
        "cancelled": summary["cancelled"] or 0,
        "rejected": summary["rejected"] or 0,
        "expired": summary["expired"] or 0,
        "blocked": summary["blocked"] or 0,
        "failed": summary["failed"] or 0,
        "buy_fills": summary["buy_fills"] or 0,
        "sell_fills": summary["sell_fills"] or 0,
        "fill_rate_pct": fill_rate,
        "execution_quality": {
            "fills_measured": quality["fills"] or 0 if quality else 0,
            "avg_slippage_bps": round(float(quality["avg_slippage"]), 2) if quality and quality["avg_slippage"] else None,
            "avg_fill_delay_sec": round(float(quality["avg_delay"]), 1) if quality and quality["avg_delay"] else None,
        },
    }
