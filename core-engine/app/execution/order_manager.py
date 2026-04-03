import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.execution.broker import BrokerClient
from app.execution.order_fsm import OrderState, generate_idempotency_key, check_duplicate_order, transition_order_state
from app.metrics import ORDERS_TOTAL
from app.services.audit import log_event
from app.execution.risk_manager import RiskManager
from app.models.execution import OrderRequest, OrderResult, RiskCheckRequest
from app.services.redis_publisher import RedisPublisher

logger = logging.getLogger(__name__)


def _build_result(
    order_id: str, request: OrderRequest, now: datetime,
    *, status: str, message: str = "", risk_checks: list | None = None,
    filled_qty: int = 0, filled_price: float | None = None,
) -> OrderResult:
    ORDERS_TOTAL.labels(side=request.side, status=status).inc()
    return OrderResult(
        order_id=order_id, stock_code=request.stock_code,
        side=request.side, order_type=request.order_type,
        quantity=request.quantity, price=request.price,
        filled_qty=filled_qty, filled_price=filled_price,
        status=status, risk_checks=risk_checks or [],
        message=message, created_at=now,
    )


async def _publish_order_event(redis: aioredis.Redis, order_id: str, request: OrderRequest, filled_qty: int, filled_price: float | None):
    try:
        publisher = RedisPublisher(redis)
        await publisher.publish_event("order_filled", {
            "order_id": order_id, "stock_code": request.stock_code,
            "side": request.side, "quantity": filled_qty, "price": filled_price,
        })
    except Exception:
        pass


async def execute_order(
    request: OrderRequest,
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    broker: BrokerClient,
    risk_mgr: RiskManager,
) -> OrderResult:
    """Execute a trading order with risk management + trading guard."""
    from app.execution.trading_guard import TradingGuard

    now = datetime.now(timezone.utc)
    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"

    # -2. Cooldown check — prevent rapid-fire retries after FAILED/BLOCKED (BUY only)
    # SELL orders (stop-loss, take-profit) are always allowed
    cooldown_key = f"order:cooldown:{request.stock_code}:{request.side}"
    if request.side == "BUY" and await redis.exists(cooldown_key):
        return _build_result(order_id, request, now, status="FAILED", message=f"쿨다운 중: {request.stock_code} {request.side} (5분 내 재시도 불가)")

    # -1. Idempotency check (v1.31 16.5.2)
    idem_key = generate_idempotency_key(request.signal_id, request.stock_code, request.side)
    if await check_duplicate_order(pool, idem_key):
        return _build_result(order_id, request, now, status="FAILED", message=f"중복 주문 차단 (idempotency_key={idem_key})")

    # 0. Trading guard (kill switch, session, stale data, broker circuit breaker)
    if request.side == "BUY":  # Guards apply to new entries only
        guard = TradingGuard(pool=pool, redis=redis)
        price_est = request.price or 0
        guard_ok, guard_violations = await guard.pre_trade_check(request.stock_code, price_est * request.quantity, price_est)
        if not guard_ok:
            msg = f"거래 안전 차단: {'; '.join(guard_violations)}"
            await _store_order(now, order_id, request, status="BLOCKED", message=msg, pool=pool, idempotency_key=idem_key)
            await redis.setex(cooldown_key, 300, "blocked")  # 5분 쿨다운
            return _build_result(order_id, request, now, status="BLOCKED", message=msg, risk_checks=guard_violations)

    portfolio_value, cash = await _get_portfolio_state(pool=pool)

    # 1. Risk check
    risk_result = await risk_mgr.check_order(
        RiskCheckRequest(
            stock_code=request.stock_code, side=request.side,
            quantity=request.quantity, price=request.price,
        ),
        portfolio_value=portfolio_value, cash=cash, pool=pool,
    )
    if not risk_result.allowed:
        msg = f"리스크 체크 실패: {'; '.join(risk_result.violations)}"
        await _store_order(now, order_id, request, status="FAILED", message=msg, pool=pool, idempotency_key=idem_key)
        await redis.setex(cooldown_key, 300, "risk_failed")  # 5분 쿨다운
        return _build_result(order_id, request, now, status="FAILED", message=msg, risk_checks=risk_result.violations)

    # 2. Store CREATED order, then VALIDATED
    await _store_order(now, order_id, request, status="CREATED", pool=pool, idempotency_key=idem_key)
    await transition_order_state(pool, order_id, OrderState.VALIDATED, "risk check passed")

    # 3. Submit to broker → SUBMITTED
    await transition_order_state(pool, order_id, OrderState.SUBMITTED, "sending to broker")
    broker_resp = await broker.submit_order(
        stock_code=request.stock_code, side=request.side,
        quantity=request.quantity, order_type=request.order_type, price=request.price,
    )

    if not broker_resp.success:
        guard = TradingGuard(pool=pool, redis=redis)
        await guard.record_broker_failure()
        await transition_order_state(pool, order_id, OrderState.REJECTED, broker_resp.message)
        return _build_result(order_id, request, now, status="REJECTED", message=broker_resp.message, risk_checks=risk_result.warnings)

    # 4. Broker ACK → determine fill status
    await transition_order_state(pool, order_id, OrderState.ACKED, f"broker order_no={broker_resp.order_no}")

    if broker_resp.filled_qty == request.quantity:
        final_status = OrderState.FILLED
    elif broker_resp.filled_qty > 0:
        final_status = OrderState.PARTIALLY_FILLED
    else:
        final_status = OrderState.ACKED  # awaiting fill

    await transition_order_state(pool, order_id, final_status, f"filled={broker_resp.filled_qty}/{request.quantity}")

    # 5. Update positions (atomic transaction)
    filled_price = broker_resp.filled_price or request.price
    if broker_resp.filled_qty > 0:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _update_position_conn(conn, request.stock_code, request.side, broker_resp.filled_qty, filled_price or 0)

    # 4. Publish event
    await _publish_order_event(redis, order_id, request, broker_resp.filled_qty, filled_price)

    # Reset broker circuit breaker on success
    guard_success = TradingGuard(pool=pool, redis=redis)
    await guard_success.reset_broker_failures()

    result = _build_result(
        order_id, request, now, status=final_status.value, message=broker_resp.message,
        risk_checks=risk_result.warnings, filled_qty=broker_resp.filled_qty, filled_price=filled_price,
    )

    # Audit log
    await log_event(
        pool, source="order", event_type=f"order_{final_status.value.lower()}",
        symbol=request.stock_code, correlation_id=order_id,
        payload={"order_id": order_id, "side": request.side, "qty": request.quantity,
                 "filled_qty": broker_resp.filled_qty, "filled_price": filled_price,
                 "status": final_status.value, "broker_order_no": broker_resp.order_no},
    )

    return result


async def _get_portfolio_state(*, pool: asyncpg.Pool) -> tuple[float, float]:
    """Get current portfolio total value and cash."""
    async with pool.acquire() as conn:
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )

    if snapshot:
        return float(snapshot["total_value"]), float(snapshot["cash"])

    # No snapshot exists: use default initial capital
    return settings.initial_capital, settings.initial_capital


async def _store_order_conn(
    conn, time: datetime, order_id: str, request: OrderRequest, status: str,
    filled_qty: int = 0, filled_price: float | None = None, message: str = "",
    idempotency_key: str | None = None,
):
    """Insert order record using an existing connection."""
    metadata = {"message": message}
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    await conn.execute(
        """INSERT INTO orders (time, order_id, stock_code, side, order_type, quantity,
            price, filled_qty, filled_price, status, signal_id, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
        time, order_id, request.stock_code, request.side, request.order_type,
        request.quantity, Decimal(str(request.price)) if request.price else None,
        filled_qty, Decimal(str(filled_price)) if filled_price else None,
        status, request.signal_id, json.dumps(metadata),
    )


async def _store_order(
    time: datetime, order_id: str, request: OrderRequest, status: str,
    filled_qty: int = 0, filled_price: float | None = None, message: str = "",
    *, pool: asyncpg.Pool, idempotency_key: str | None = None,
):
    """Insert order record (acquires its own connection)."""
    async with pool.acquire() as conn:
        await _store_order_conn(conn, time, order_id, request, status, filled_qty, filled_price, message, idempotency_key)


async def _update_position_conn(conn, stock_code: str, side: str, quantity: int, price: float):
    """Update portfolio_positions using an existing connection."""
    existing = await conn.fetchrow(
        "SELECT id, quantity, avg_price FROM portfolio_positions WHERE stock_code = $1", stock_code,
    )

    if side == "BUY":
        if existing:
            old_qty = existing["quantity"]
            old_avg = float(existing["avg_price"])
            new_qty = old_qty + quantity
            new_avg = (old_qty * old_avg + quantity * price) / new_qty if new_qty > 0 else price
            await conn.execute(
                "UPDATE portfolio_positions SET quantity = $1, avg_price = $2, current_price = $3, updated_at = NOW() WHERE stock_code = $4",
                new_qty, Decimal(str(round(new_avg, 2))), Decimal(str(price)), stock_code,
            )
        else:
            await conn.execute(
                "INSERT INTO portfolio_positions (stock_code, quantity, avg_price, current_price) VALUES ($1, $2, $3, $4)",
                stock_code, quantity, Decimal(str(price)), Decimal(str(price)),
            )
    elif side == "SELL" and existing:
        new_qty = existing["quantity"] - quantity
        if new_qty <= 0:
            await conn.execute("DELETE FROM portfolio_positions WHERE stock_code = $1", stock_code)
        else:
            await conn.execute(
                "UPDATE portfolio_positions SET quantity = $1, current_price = $2, updated_at = NOW() WHERE stock_code = $3",
                new_qty, Decimal(str(price)), stock_code,
            )
