"""Fill monitor — tracks ACKED/SUBMITTED orders until final resolution.

Polls broker for order status updates and transitions orders to their
final state (FILLED, CANCELLED, REJECTED, EXPIRED).

Also records execution quality metrics (slippage, fill time).
"""

import logging
from datetime import datetime, timezone, timedelta

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.execution.order_fsm import OrderState, transition_order_state
from app.services.audit import log_event
from app.services.kis_api import KISClient
from app.utils.market_calendar import KST

logger = logging.getLogger(__name__)

# Thresholds
STALE_ORDER_MINUTES = 5       # Alert if order is unresolved after this
AUTO_CANCEL_MINUTES = 30      # Auto-cancel if unresolved after this
SLIPPAGE_ALERT_BPS = 50       # Alert if slippage exceeds 50 basis points


async def check_inflight_orders(
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
) -> dict:
    """Check all in-flight orders and update their status.

    Should be called periodically (every 10-30 seconds during trading hours).

    Returns summary of actions taken.
    """
    now = datetime.now(timezone.utc)
    results = {"checked": 0, "updated": 0, "stale_alerts": 0, "cancelled": 0, "errors": []}

    async with pool.acquire() as conn:
        inflight = await conn.fetch(
            """
            SELECT order_id, stock_code, side, quantity, price, status, time,
                   metadata::text as metadata_str
            FROM orders
            WHERE status IN ('SUBMITTED', 'ACKED', 'PARTIALLY_FILLED')
              AND time > NOW() - INTERVAL '1 day'
            ORDER BY time ASC
            """
        )

    results["checked"] = len(inflight)

    if not inflight:
        return results

    # Try to get broker order status for each
    for order in inflight:
        order_id = order["order_id"]
        order_time = order["time"]
        age_minutes = (now - order_time).total_seconds() / 60

        try:
            # Check if order is stale
            if age_minutes > STALE_ORDER_MINUTES:
                results["stale_alerts"] += 1
                logger.warning(
                    "Stale order detected: %s (%s %s) age=%.1f min",
                    order_id, order["side"], order["stock_code"], age_minutes,
                )

            # Auto-cancel very old orders
            if age_minutes > AUTO_CANCEL_MINUTES:
                await _cancel_stale_order(pool, order_id, order["stock_code"], age_minutes)
                results["cancelled"] += 1
                continue

            # Try broker status inquiry
            fill_info = await _query_broker_fill(kis_client, order)
            if fill_info:
                await _process_fill_update(pool, redis, order, fill_info)
                results["updated"] += 1

        except Exception as e:
            results["errors"].append(f"{order_id}: {e}")
            logger.error("Fill monitor error for %s: %s", order_id, e)

    return results


async def _query_broker_fill(kis_client: KISClient, order: dict) -> dict | None:
    """Query KIS API for order fill status.

    Uses 주식주문체결조회 API (TTTC8001R / VTTC8001R).
    Returns fill info dict or None if no update available.
    """
    if not settings.kis_app_key:
        return None  # No broker connection in simulation mode

    try:
        tr_id = "VTTC8001R" if "vts" in settings.kis_base_url else "TTTC8001R"

        # Extract broker order_no from metadata
        import json
        metadata = json.loads(order["metadata_str"]) if order["metadata_str"] else {}
        broker_order_no = None
        for key in ("broker_order_no", "order_no"):
            if key in metadata:
                broker_order_no = metadata[key]
                break

        if not broker_order_no:
            return None

        now_kst = datetime.now(KST)
        data = await kis_client._request_with_retry(
            "GET",
            f"{settings.kis_base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            tr_id=tr_id,
            params={
                "CANO": settings.kis_cano,
                "ACNT_PRDT_CD": settings.kis_acnt_prdt_cd,
                "INQR_STRT_DT": now_kst.strftime("%Y%m%d"),
                "INQR_END_DT": now_kst.strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",  # All
                "INQR_DVSN": "00",
                "PDNO": order["stock_code"],
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": broker_order_no,
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )

        for item in data.get("output1", []):
            if item.get("odno") == broker_order_no:
                filled_qty = int(item.get("tot_ccld_qty", "0"))
                filled_price = float(item.get("avg_prvs", "0"))
                order_qty = int(item.get("ord_qty", "0"))
                cancel_qty = int(item.get("cncl_cfrm_qty", "0"))

                if cancel_qty > 0 and filled_qty == 0:
                    return {"status": "CANCELLED", "filled_qty": 0, "filled_price": 0}
                elif filled_qty >= order_qty:
                    return {"status": "FILLED", "filled_qty": filled_qty, "filled_price": filled_price}
                elif filled_qty > 0:
                    return {"status": "PARTIALLY_FILLED", "filled_qty": filled_qty, "filled_price": filled_price}

        return None  # No update found

    except Exception as e:
        logger.debug("Broker fill query failed for %s: %s", order["order_id"], e)
        return None


async def _process_fill_update(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    order: dict,
    fill_info: dict,
):
    """Process a fill status update from the broker."""
    order_id = order["order_id"]
    new_status = fill_info["status"]
    filled_qty = fill_info["filled_qty"]
    filled_price = fill_info["filled_price"]

    current_status = order["status"]
    target_state = OrderState(new_status)

    # Only transition if status actually changed
    if current_status == new_status:
        return

    await transition_order_state(
        pool, order_id, target_state,
        f"fill_monitor: filled={filled_qty}, price={filled_price}",
    )

    # Update order record with fill details
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE orders SET filled_qty = $1, filled_price = $2, status = $3
            WHERE order_id = $4 AND time > NOW() - INTERVAL '1 day'""",
            filled_qty, filled_price, new_status, order_id,
        )

        # Record execution quality (slippage)
        if filled_price and order["price"]:
            signal_price = float(order["price"])
            if signal_price > 0:
                slippage_bps = round((filled_price - signal_price) / signal_price * 10000, 2)
                side_factor = 1 if order["side"] == "BUY" else -1
                # For BUY: positive slippage = paid more (bad)
                # For SELL: negative slippage = received less (bad)
                effective_slippage = slippage_bps * side_factor

                await conn.execute(
                    """INSERT INTO execution_quality
                    (time, order_id, stock_code, side, signal_price, fill_price,
                     slippage_bps, fill_delay_seconds)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    datetime.now(timezone.utc),
                    order_id,
                    order["stock_code"],
                    order["side"],
                    signal_price,
                    filled_price,
                    effective_slippage,
                    (datetime.now(timezone.utc) - order["time"]).total_seconds(),
                )

                if abs(effective_slippage) > SLIPPAGE_ALERT_BPS:
                    logger.warning(
                        "High slippage: %s %s %s slippage=%.1f bps",
                        order_id, order["side"], order["stock_code"], effective_slippage,
                    )

    # Update position if newly filled
    if new_status == "FILLED" and current_status != "FILLED" and filled_qty > 0:
        from app.execution.order_manager import _update_position_conn
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _update_position_conn(
                    conn, order["stock_code"], order["side"],
                    filled_qty, filled_price,
                )

    await log_event(
        pool, source="fill_monitor", event_type=f"fill_{new_status.lower()}",
        symbol=order["stock_code"], correlation_id=order_id,
        payload={
            "order_id": order_id,
            "prev_status": current_status,
            "new_status": new_status,
            "filled_qty": filled_qty,
            "filled_price": filled_price,
        },
    )

    logger.info(
        "Fill update: %s %s→%s filled=%d@%.0f",
        order_id, current_status, new_status, filled_qty, filled_price or 0,
    )


async def _cancel_stale_order(
    pool: asyncpg.Pool,
    order_id: str,
    stock_code: str,
    age_minutes: float,
):
    """Mark a stale order as EXPIRED and log it."""
    await transition_order_state(
        pool, order_id, OrderState.EXPIRED,
        f"auto-expired: age={age_minutes:.0f}min > {AUTO_CANCEL_MINUTES}min threshold",
    )

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET status = 'EXPIRED' WHERE order_id = $1 AND time > NOW() - INTERVAL '1 day'",
            order_id,
        )

    await log_event(
        pool, source="fill_monitor", event_type="order_expired",
        symbol=stock_code, correlation_id=order_id,
        payload={"reason": "stale_timeout", "age_minutes": round(age_minutes, 1)},
    )

    logger.warning("Auto-expired stale order: %s (age=%.0f min)", order_id, age_minutes)


async def get_execution_quality_stats(
    *,
    pool: asyncpg.Pool,
    days: int = 30,
) -> dict:
    """Get execution quality statistics for recent orders."""
    async with pool.acquire() as conn:
        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total_fills,
                AVG(slippage_bps) as avg_slippage_bps,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY slippage_bps) as median_slippage_bps,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps) as p95_slippage_bps,
                MAX(ABS(slippage_bps)) as max_slippage_bps,
                AVG(fill_delay_seconds) as avg_fill_delay_sec,
                COUNT(CASE WHEN ABS(slippage_bps) > $2 THEN 1 END) as high_slippage_count
            FROM execution_quality
            WHERE time > NOW() - make_interval(days => $1)
            """,
            days, float(SLIPPAGE_ALERT_BPS),
        )

        by_side = await conn.fetch(
            """
            SELECT side,
                COUNT(*) as fills,
                AVG(slippage_bps) as avg_slippage_bps
            FROM execution_quality
            WHERE time > NOW() - make_interval(days => $1)
            GROUP BY side
            """,
            days,
        )

    if not stats or stats["total_fills"] == 0:
        return {"total_fills": 0, "message": "No execution data available"}

    return {
        "period_days": days,
        "total_fills": stats["total_fills"],
        "avg_slippage_bps": round(float(stats["avg_slippage_bps"]), 2),
        "median_slippage_bps": round(float(stats["median_slippage_bps"]), 2),
        "p95_slippage_bps": round(float(stats["p95_slippage_bps"]), 2),
        "max_slippage_bps": round(float(stats["max_slippage_bps"]), 2),
        "avg_fill_delay_sec": round(float(stats["avg_fill_delay_sec"]), 1),
        "high_slippage_count": stats["high_slippage_count"],
        "by_side": [
            {"side": r["side"], "fills": r["fills"], "avg_slippage_bps": round(float(r["avg_slippage_bps"]), 2)}
            for r in by_side
        ],
    }
