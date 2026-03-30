"""Morning Momentum Scanner (장초반 모멘텀 스캐너)

09:00~09:30 KST 정규장 초반 비정상적 움직임을 포착하여 자동매매.
Outside that window the scanner returns a blocked status and does nothing.
"""

import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.execution.broker import BrokerClient
from app.execution.order_manager import execute_order
from app.execution.risk_manager import RiskManager
from app.models.execution import OrderRequest
from app.services.kis_api import KISClient
from app.services.notification import NotificationService
from app.services.redis_publisher import RedisPublisher
from app.trading.position_sizer import calculate_quantity
from app.utils.market_calendar import KST, MarketSession, get_current_session

logger = logging.getLogger(__name__)


async def run_morning_scan(
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    kis_client: KISClient,
    broker: BrokerClient,
    risk_mgr: RiskManager,
    notifier: NotificationService,
    now: datetime | None = None,
) -> dict:
    """Scan all universe stocks for morning momentum and auto-trade."""
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)
    session, description = get_current_session(now_kst)

    # Morning scan is only valid during the early regular session.
    if session != MarketSession.REGULAR or now_kst.time() >= datetime.strptime("09:30", "%H:%M").time():
        return {
            "status": "blocked",
            "message": f"장초반 스캔 허용 시간 아님: {description}",
            "scanned_at": now_utc.isoformat(),
            "kst_time": now_kst.strftime("%H:%M:%S"),
            "allowed_window": "09:00~09:30 KST",
        }

    universe = await _fetch_universe(pool=pool)
    if not universe:
        return {"status": "empty", "message": "유니버스가 비어있습니다"}

    movers = await _scan_prices(universe, now_utc, pool=pool, kis_client=kis_client)
    if not movers:
        return {"status": "no_data", "message": "시세 조회 실패 (장외시간 가능성)"}

    movers.sort(key=lambda x: abs(x["momentum_score"]), reverse=True)
    await _send_surge_alerts(movers, notifier=notifier)

    gap_up = [m for m in movers if m["change_pct"] >= settings.scanner_gap_threshold * 100]
    gap_down = [m for m in movers if m["change_pct"] <= -settings.scanner_gap_threshold * 100]

    orders_placed = await _auto_trade_gap_up(
        gap_up, pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr,
    )
    await _publish_scan_event(movers, gap_up, gap_down, orders_placed, redis=redis)

    return {
        "status": "success",
        "scanned_at": now_utc.isoformat(),
        "total_scanned": len(movers),
        "top_movers": movers[:settings.scanner_top_n],
        "gap_up": gap_up[:5],
        "gap_down": gap_down[:5],
        "orders_placed": orders_placed,
        "summary": {
            "strongest": movers[0] if movers else None,
            "weakest": movers[-1] if movers else None,
            "avg_change_pct": round(sum(m["change_pct"] for m in movers) / len(movers), 2),
        },
    }


async def _fetch_universe(*, pool: asyncpg.Pool) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT stock_code, stock_name FROM stocks WHERE stock_code IN "
            "(SELECT stock_code FROM universe WHERE is_active = TRUE)"
        )


async def _scan_prices(universe, now, *, pool: asyncpg.Pool, kis_client: KISClient) -> list:
    movers = []

    for row in universe:
        code, name = row["stock_code"], row["stock_name"]
        try:
            current = await kis_client.get_current_price(code)
            if not current:
                continue

            async with pool.acquire() as conn:
                prev = await conn.fetchrow(
                    "SELECT close, volume FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
                    code,
                )

            if not prev or float(prev["close"]) <= 0:
                continue

            current_price = float(current.close)
            prev_close = float(prev["close"])
            prev_volume = int(prev["volume"]) if prev["volume"] else 0
            change_pct = (current_price - prev_close) / prev_close
            volume_ratio = current.volume / max(prev_volume, 1)

            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, interval) VALUES ($1,$2,$3,$4,$5,$6,$7,'1m')",
                    now, code, current.open, current.high, current.low, current.close, current.volume,
                )

            movers.append({
                "stock_code": code, "stock_name": name,
                "current_price": current_price, "prev_close": prev_close,
                "change_pct": round(change_pct * 100, 2),
                "volume_ratio": round(volume_ratio, 2),
                "momentum_score": _calc_momentum_score(change_pct, volume_ratio),
            })
        except Exception as e:
            logger.error("Scan failed for %s: %s", code, e)

    return movers


async def _send_surge_alerts(movers, *, notifier: NotificationService):
    for m in movers:
        if abs(m["change_pct"]) >= settings.scanner_price_surge_alert_pct:
            await notifier.alert_price_surge(
                m["stock_name"], m["stock_code"], m["change_pct"], m["current_price"], 0,
            )


async def _auto_trade_gap_up(
    gap_up,
    *,
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    broker: BrokerClient,
    risk_mgr: RiskManager,
) -> list:
    async with pool.acquire() as conn:
        snapshot = await conn.fetchrow("SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1")
        positions = await conn.fetch("SELECT stock_code FROM portfolio_positions WHERE quantity > 0")

    portfolio_value = float(snapshot["total_value"]) if snapshot else settings.initial_capital
    cash = float(snapshot["cash"]) if snapshot else settings.initial_capital
    held_codes = {p["stock_code"] for p in positions}

    orders = []
    buy_count = 0

    for mover in gap_up[:settings.scanner_top_n]:
        if buy_count >= settings.scanner_max_buy_per_scan or mover["stock_code"] in held_codes:
            continue

        strength = min(abs(mover["momentum_score"]) / 100, 1.0)
        qty = calculate_quantity(strength, portfolio_value, cash, mover["current_price"])
        if qty <= 0:
            continue

        try:
            result = await execute_order(
                OrderRequest(stock_code=mover["stock_code"], side="BUY", quantity=qty, signal_id="morning_momentum"),
                pool=pool, redis=redis, broker=broker, risk_mgr=risk_mgr,
            )
            orders.append({
                "stock_code": mover["stock_code"], "stock_name": mover["stock_name"],
                "change_pct": mover["change_pct"], "quantity": qty, "status": result.status,
            })
            if result.status == "FILLED":
                buy_count += 1
                cash -= qty * mover["current_price"]
        except Exception as e:
            logger.error("Morning buy failed for %s: %s", mover["stock_code"], e)

    return orders


async def _publish_scan_event(movers, gap_up, gap_down, orders, *, redis: aioredis.Redis):
    try:
        publisher = RedisPublisher(redis)
        await publisher.publish_event("morning_scan", {
            "top_movers": min(len(movers), settings.scanner_top_n),
            "gap_up": len(gap_up), "gap_down": len(gap_down), "orders": len(orders),
        })
    except Exception:
        pass


def _calc_momentum_score(change_pct: float, volume_ratio: float) -> float:
    """Momentum score = price change * volume amplifier."""
    price_score = change_pct * 100
    vol_multiplier = max(min(volume_ratio / 2, 3.0), 0.5)
    return round(price_score * vol_multiplier, 2)
