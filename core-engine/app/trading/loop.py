"""Trading loop orchestrator: full cycle from data collection to order execution."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.execution.broker import BrokerClient
from app.metrics import PORTFOLIO_VALUE
from app.execution.order_manager import execute_order
from app.execution.risk_manager import RiskManager
from app.models.execution import OrderRequest
from app.services.kis_api import KISClient
from app.services.naver_news import NaverNewsClient
from app.services.notification import NotificationService
from app.services.redis_publisher import RedisPublisher
from app.strategy.ensemble import generate_signal
from app.trading.position_sizer import calculate_quantity, calculate_sell_quantity

logger = logging.getLogger(__name__)


async def run_trading_cycle(
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
    naver_client: NaverNewsClient,
    broker: BrokerClient,
    risk_mgr: RiskManager,
    notifier: NotificationService,
) -> dict:
    """Execute one full trading cycle."""
    from app.trading.monitor import check_positions

    now = datetime.now(timezone.utc)
    result = {"started_at": now.isoformat(), "steps": {}, "orders_placed": [], "errors": []}

    result["steps"]["collect_ohlcv"] = await _step_collect_ohlcv(result["errors"], pool=pool, redis=redis, kis_client=kis_client)
    result["steps"]["collect_news"] = await _step_collect_news(result["errors"], pool=pool, naver_client=naver_client)

    signals = await _step_generate_signals(result["errors"], pool=pool, redis=redis)
    buy_signals = [s for s in signals if s.signal == "BUY"]
    sell_signals = [s for s in signals if s.signal == "SELL"]
    result["steps"]["signals"] = {
        "total": len(signals), "buy": len(buy_signals),
        "sell": len(sell_signals), "hold": len(signals) - len(buy_signals) - len(sell_signals),
    }

    portfolio_value, cash, held_codes = await _get_portfolio_state(pool=pool)
    await _execute_buys(buy_signals, portfolio_value, cash, held_codes, result, pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr)
    await _execute_sells(sell_signals, held_codes, result, pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr)

    try:
        result["steps"]["monitor"] = await check_positions(pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr, notifier=notifier)
    except Exception as e:
        result["errors"].append(f"Monitor failed: {e}")

    try:
        result["steps"]["snapshot"] = await save_portfolio_snapshot(pool=pool)
    except Exception as e:
        result["errors"].append(f"Snapshot failed: {e}")

    await _publish_cycle_complete(result, redis=redis)
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "success" if not result["errors"] else "partial"
    return result


# --- Step functions ---


async def _step_collect_ohlcv(errors: list, *, pool: asyncpg.Pool, redis: aioredis.Redis, kis_client: KISClient) -> dict:
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE")
        stock_codes = [r["stock_code"] for r in rows]

        inserted = 0
        publisher = RedisPublisher(redis)
        for code in stock_codes:
            try:
                record = await kis_client.get_current_price(code)
                if not record:
                    continue
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'1d')",
                        record.time, record.stock_code, record.open, record.high, record.low, record.close, record.volume, record.value,
                    )
                    inserted += 1
                await publisher.publish_ohlcv(code, record.model_dump(mode="json"))
            except Exception as e:
                errors.append(f"OHLCV failed for {code}: {e}")
        return {"status": "success", "inserted": inserted}
    except Exception as e:
        errors.append(f"OHLCV collection failed: {e}")
        return {"status": "error"}


async def _step_collect_news(errors: list, *, pool: asyncpg.Pool, naver_client: NaverNewsClient) -> dict:
    try:
        records = await naver_client.fetch_rss_news()
        inserted = 0
        async with pool.acquire() as conn:
            for rec in records:
                try:
                    if rec.url:
                        exists = await conn.fetchval("SELECT 1 FROM news WHERE url = $1 LIMIT 1", rec.url)
                        if exists:
                            continue
                    await conn.execute(
                        "INSERT INTO news (time, source, title, content, url, stock_codes, category, is_processed) VALUES ($1,$2,$3,$4,$5,$6,$7,FALSE)",
                        rec.time, rec.source, rec.title, rec.content, rec.url, rec.stock_codes, rec.category,
                    )
                    inserted += 1
                except Exception as e:
                    errors.append(f"News insert failed: {e}")
        return {"status": "success", "inserted": inserted}
    except Exception as e:
        errors.append(f"News collection failed: {e}")
        return {"status": "error"}


async def _step_generate_signals(errors: list, *, pool: asyncpg.Pool, redis: aioredis.Redis) -> list:
    async with pool.acquire() as conn:
        universe = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE")

    signals = []
    for row in universe:
        try:
            signals.append(await generate_signal(row["stock_code"], pool=pool, redis=redis))
        except Exception as e:
            errors.append(f"Signal failed for {row['stock_code']}: {e}")
    return signals


async def _get_portfolio_state(*, pool: asyncpg.Pool) -> tuple[float, float, dict]:
    async with pool.acquire() as conn:
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )
        positions = await conn.fetch(
            "SELECT stock_code, quantity, avg_price FROM portfolio_positions WHERE quantity > 0"
        )
    pv = float(snapshot["total_value"]) if snapshot else settings.initial_capital
    cash = float(snapshot["cash"]) if snapshot else settings.initial_capital
    held = {p["stock_code"]: p for p in positions}
    return pv, cash, held


async def _execute_buys(
    buy_signals, portfolio_value, cash, held_codes, result,
    *, pool: asyncpg.Pool, redis: aioredis.Redis, broker: BrokerClient, risk_mgr: RiskManager,
):
    for sig in buy_signals:
        existing_qty = held_codes[sig.stock_code]["quantity"] if sig.stock_code in held_codes else 0
        existing_avg = float(held_codes[sig.stock_code]["avg_price"]) if sig.stock_code in held_codes else 0

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT close FROM ohlcv WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", sig.stock_code
            )
        price = float(row["close"]) if row else 0
        if price <= 0:
            continue

        qty = calculate_quantity(sig.strength, portfolio_value, cash, price, existing_qty, existing_avg)
        if qty <= 0:
            continue

        try:
            order = await execute_order(
                OrderRequest(stock_code=sig.stock_code, side="BUY", quantity=qty),
                pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr,
            )
            result["orders_placed"].append({"stock_code": sig.stock_code, "side": "BUY", "quantity": qty, "status": order.status})
            if order.status == "FILLED" and order.filled_price:
                cash -= qty * order.filled_price
        except Exception as e:
            result["errors"].append(f"BUY failed for {sig.stock_code}: {e}")


async def _execute_sells(
    sell_signals, held_codes, result,
    *, pool: asyncpg.Pool, redis: aioredis.Redis, broker: BrokerClient, risk_mgr: RiskManager,
):
    for sig in sell_signals:
        if sig.stock_code not in held_codes:
            continue
        sell_qty = calculate_sell_quantity(held_codes[sig.stock_code]["quantity"], sig.strength)
        if sell_qty <= 0:
            continue
        try:
            order = await execute_order(
                OrderRequest(stock_code=sig.stock_code, side="SELL", quantity=sell_qty),
                pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr,
            )
            result["orders_placed"].append({"stock_code": sig.stock_code, "side": "SELL", "quantity": sell_qty, "status": order.status})
        except Exception as e:
            result["errors"].append(f"SELL failed for {sig.stock_code}: {e}")


async def _publish_cycle_complete(result, *, redis: aioredis.Redis):
    try:
        publisher = RedisPublisher(redis)
        await publisher.publish_event("cycle_complete", {
            "orders": len(result["orders_placed"]), "errors": len(result["errors"]),
        })
    except Exception:
        pass


# --- Portfolio Snapshot ---


async def save_portfolio_snapshot(*, pool: asyncpg.Pool) -> dict:
    """Calculate and store a portfolio snapshot."""
    now = datetime.now(timezone.utc)

    positions, prev = await _fetch_snapshot_data(pool)
    total_value, cash, invested, market_value = _calc_portfolio_values(positions, prev)
    daily_pnl, daily_return, cumulative_return = _calc_returns(total_value, prev)
    max_dd = await _calc_mdd(pool, total_value)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO portfolio_snapshots
                (time, total_value, cash, invested, daily_pnl, daily_return,
                 cumulative_return, mdd, positions_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            now,
            Decimal(str(round(total_value, 2))), Decimal(str(round(cash, 2))),
            Decimal(str(round(invested, 2))), Decimal(str(round(daily_pnl, 2))),
            Decimal(str(round(daily_return, 6))), Decimal(str(round(cumulative_return, 6))),
            Decimal(str(round(max_dd, 6))), len(positions),
        )

    PORTFOLIO_VALUE.set(total_value)

    return {
        "time": now.isoformat(), "total_value": round(total_value, 0),
        "cash": round(cash, 0), "daily_pnl": round(daily_pnl, 0),
        "daily_return_pct": round(daily_return * 100, 2),
        "cumulative_return_pct": round(cumulative_return * 100, 2),
        "mdd_pct": round(max_dd * 100, 2), "positions": len(positions),
    }


async def _fetch_snapshot_data(pool):
    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """SELECT pp.stock_code, pp.quantity, pp.avg_price,
                      (SELECT close FROM ohlcv WHERE stock_code = pp.stock_code ORDER BY time DESC LIMIT 1) as current_price
               FROM portfolio_positions pp WHERE pp.quantity > 0"""
        )
        prev = await conn.fetchrow("SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1")
    return positions, prev


def _calc_portfolio_values(positions, prev):
    initial = settings.initial_capital
    cash = float(prev["cash"]) if prev else initial
    invested = sum(p["quantity"] * float(p["avg_price"]) for p in positions)
    market_value = sum(p["quantity"] * float(p["current_price"] or p["avg_price"]) for p in positions)
    return cash + market_value, cash, invested, market_value


def _calc_returns(total_value, prev):
    initial = settings.initial_capital
    prev_total = float(prev["total_value"]) if prev else initial
    daily_pnl = total_value - prev_total
    daily_return = daily_pnl / prev_total if prev_total > 0 else 0
    cumulative_return = (total_value / initial) - 1
    return daily_pnl, daily_return, cumulative_return


async def _calc_mdd(pool, total_value):
    async with pool.acquire() as conn:
        history = await conn.fetch("SELECT total_value FROM portfolio_snapshots ORDER BY time ASC")
    peak = settings.initial_capital
    max_dd = 0.0
    for h in history:
        val = float(h["total_value"])
        peak = max(peak, val)
        max_dd = min(max_dd, (val - peak) / peak)
    peak = max(peak, total_value)
    max_dd = min(max_dd, (total_value - peak) / peak)
    return max_dd
