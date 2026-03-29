import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from app.deps import get_db, get_redis, get_broker, get_risk_manager
from app.execution.broker import BrokerClient
from app.execution.order_manager import execute_order, _get_portfolio_state
from app.execution.risk_manager import RiskManager
from app.models.execution import (
    OrderHistoryItem,
    OrderRequest,
    OrderResult,
    RiskCheckRequest,
    RiskCheckResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/execute", response_model=OrderResult)
async def api_execute_order(
    request: OrderRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    broker: BrokerClient = Depends(get_broker),
    risk_mgr: RiskManager = Depends(get_risk_manager),
):
    """Execute a trading order with risk management."""
    return await execute_order(request, pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr)


@router.get("/history", response_model=list[OrderHistoryItem])
async def api_order_history(
    pool: asyncpg.Pool = Depends(get_db),
    stock_code: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    """Get order history."""
    async with pool.acquire() as conn:
        if stock_code:
            rows = await conn.fetch(
                """
                SELECT order_id, time, stock_code, side, order_type, quantity,
                    price, filled_qty, filled_price, status, slippage, commission
                FROM orders
                WHERE stock_code = $1
                ORDER BY time DESC
                LIMIT $2
                """,
                stock_code,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT order_id, time, stock_code, side, order_type, quantity,
                    price, filled_qty, filled_price, status, slippage, commission
                FROM orders
                ORDER BY time DESC
                LIMIT $1
                """,
                limit,
            )

    return [
        OrderHistoryItem(
            order_id=r["order_id"],
            time=r["time"],
            stock_code=r["stock_code"],
            side=r["side"],
            order_type=r["order_type"],
            quantity=r["quantity"],
            price=float(r["price"]) if r["price"] else None,
            filled_qty=r["filled_qty"],
            filled_price=float(r["filled_price"]) if r["filled_price"] else None,
            status=r["status"],
            slippage=float(r["slippage"]) if r["slippage"] else None,
            commission=float(r["commission"]) if r["commission"] else None,
        )
        for r in rows
    ]


@router.post("/risk/check", response_model=RiskCheckResult)
async def api_risk_check(
    request: RiskCheckRequest,
    pool: asyncpg.Pool = Depends(get_db),
    risk_mgr: RiskManager = Depends(get_risk_manager),
):
    """Pre-trade risk check."""
    portfolio_value, cash = await _get_portfolio_state(pool=pool)
    return await risk_mgr.check_order(request, portfolio_value, cash, pool=pool)
