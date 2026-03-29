"""Monitor positions for stop-loss and take-profit conditions."""

import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.execution.broker import BrokerClient
from app.execution.order_manager import execute_order
from app.execution.risk_manager import RiskManager
from app.models.execution import OrderRequest
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)


async def check_positions(
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    broker: BrokerClient,
    risk_mgr: RiskManager,
    notifier: NotificationService,
) -> dict:
    """Check all positions for stop-loss / take-profit triggers.

    Returns summary of actions taken.
    """
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """
            SELECT pp.stock_code, pp.quantity, pp.avg_price,
                   (SELECT close FROM ohlcv WHERE stock_code = pp.stock_code
                    ORDER BY time DESC LIMIT 1) as current_price
            FROM portfolio_positions pp
            WHERE pp.quantity > 0
            """
        )

    stop_loss_triggered = []
    take_profit_triggered = []
    errors = []

    for pos in positions:
        stock_code = pos["stock_code"]
        quantity = pos["quantity"]
        avg_price = float(pos["avg_price"])
        current_price = float(pos["current_price"]) if pos["current_price"] else None

        if not current_price or avg_price <= 0:
            continue

        # Check stop-loss
        if await risk_mgr.check_stop_loss(stock_code, avg_price, current_price):
            pnl_pct = (current_price / avg_price - 1) * 100
            logger.warning(
                "STOP-LOSS triggered: %s at %.1f%% (avg=%.0f, curr=%.0f)",
                stock_code, pnl_pct, avg_price, current_price,
            )
            try:
                result = await execute_order(
                    OrderRequest(
                        stock_code=stock_code,
                        side="SELL",
                        quantity=quantity,
                        signal_id="stop_loss",
                    ),
                    pool=pool,
                    redis=redis,
                    broker=broker,
                    risk_mgr=risk_mgr,
                )
                stop_loss_triggered.append({
                    "stock_code": stock_code,
                    "pnl_pct": round(pnl_pct, 2),
                    "quantity": quantity,
                    "order_status": result.status,
                })
                await notifier.alert_stop_loss(stock_code, stock_code, pnl_pct, quantity)
            except Exception as e:
                errors.append(f"Stop-loss sell failed for {stock_code}: {e}")

        # Check take-profit
        elif await risk_mgr.check_take_profit(stock_code, avg_price, current_price):
            pnl_pct = (current_price / avg_price - 1) * 100
            logger.info(
                "TAKE-PROFIT triggered: %s at +%.1f%%",
                stock_code, pnl_pct,
            )
            try:
                result = await execute_order(
                    OrderRequest(
                        stock_code=stock_code,
                        side="SELL",
                        quantity=quantity,
                        signal_id="take_profit",
                    ),
                    pool=pool,
                    redis=redis,
                    broker=broker,
                    risk_mgr=risk_mgr,
                )
                take_profit_triggered.append({
                    "stock_code": stock_code,
                    "pnl_pct": round(pnl_pct, 2),
                    "quantity": quantity,
                    "order_status": result.status,
                })
                await notifier.alert_take_profit(stock_code, stock_code, pnl_pct, quantity)
            except Exception as e:
                errors.append(f"Take-profit sell failed for {stock_code}: {e}")

    return {
        "checked_at": now.isoformat(),
        "positions_checked": len(positions),
        "stop_loss_triggered": stop_loss_triggered,
        "take_profit_triggered": take_profit_triggered,
        "errors": errors,
    }
