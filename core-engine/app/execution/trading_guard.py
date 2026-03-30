"""Trading guard — kill switch, session guard, stale data gate, broker circuit breaker.

Central safety layer that must be checked BEFORE any order submission.
All guards are fail-safe: if state is unknown, trading is blocked.
"""

import logging
from datetime import datetime, time, timezone, timedelta

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.services.audit import log_event
from app.utils.market_calendar import (
    KST,
    MarketSession,
    get_current_session,
    is_trading_day,
)

logger = logging.getLogger(__name__)

KILL_SWITCH_KEY = "trading:kill_switch"
BROKER_FAIL_KEY = "trading:broker_failures"


class TradingGuard:
    """Centralized pre-trade safety checks per v1.31 Section 16.5."""

    def __init__(self, pool: asyncpg.Pool, redis: aioredis.Redis):
        self.pool = pool
        self.redis = redis

    # === Kill Switch ===

    async def is_kill_switch_active(self) -> bool:
        """Check if kill switch is currently engaged."""
        val = await self.redis.get(KILL_SWITCH_KEY)
        return val == "active"

    async def activate_kill_switch(self, reason: str, operator: str = "system"):
        """Activate kill switch — blocks ALL new orders."""
        await self.redis.set(KILL_SWITCH_KEY, "active")
        logger.critical("KILL SWITCH ACTIVATED: %s (by %s)", reason, operator)
        await log_event(
            self.pool, source="kill_switch", event_type="activated",
            operator_id=operator, payload={"reason": reason},
        )

    async def deactivate_kill_switch(self, operator: str = "operator"):
        """Deactivate kill switch — requires manual operator action."""
        await self.redis.delete(KILL_SWITCH_KEY)
        logger.warning("Kill switch deactivated by %s", operator)
        await log_event(
            self.pool, source="kill_switch", event_type="deactivated",
            operator_id=operator, payload={"action": "deactivated"},
        )

    # === Daily Loss Auto Kill ===

    async def check_daily_loss(self) -> tuple[bool, float]:
        """Check if daily loss exceeds limit. Returns (ok, loss_pct).
        If not ok, kill switch is automatically activated.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT daily_pnl, total_value FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
            )
        if not row or not row["total_value"]:
            return True, 0.0

        total = float(row["total_value"])
        daily_pnl = float(row["daily_pnl"]) if row["daily_pnl"] else 0.0
        loss_pct = daily_pnl / total if total > 0 else 0.0

        if loss_pct <= settings.risk_max_daily_loss_pct:
            await self.activate_kill_switch(
                f"일간 손실 한도 초과: {loss_pct:.2%} <= {settings.risk_max_daily_loss_pct:.0%}"
            )
            return False, loss_pct

        return True, loss_pct

    # === Session Guard ===

    def is_trading_session(self) -> tuple[bool, str, dict]:
        """Check if current time is within allowed trading session.

        Uses full KOSPI/KOSDAQ market calendar with holiday awareness.
        - New entries allowed only during REGULAR session window:
          09:00 + open_delay ~ 15:20 - close_buffer
        - PRE_MARKET / AFTER_HOURS: monitoring only, no new entries.

        Returns:
            (allowed, reason, session_info)
        """
        now_kst = datetime.now(KST)
        session, description = get_current_session(now_kst)
        current_time = now_kst.time()

        session_info = {
            "session": session.value,
            "description": description,
            "kst_time": now_kst.strftime("%H:%M:%S"),
            "is_trading_day": is_trading_day(now_kst.date()),
        }

        # Non-trading day or CLOSED
        if session == MarketSession.CLOSED:
            return False, description, session_info

        # PRE_MARKET / OPENING_AUCTION: block new entries, allow monitoring
        if session in (MarketSession.PRE_MARKET, MarketSession.OPENING_AUCTION):
            return (
                False,
                f"{description} — 신규 진입 불가 (모니터링만 허용)",
                session_info,
            )

        # REGULAR session: apply open delay and close buffer
        if session == MarketSession.REGULAR:
            open_with_delay = time(9, settings.risk_session_open_delay_min)
            # close_buffer minutes before regular close (15:20)
            close_buffer_hour = 15
            close_buffer_min = 20 - settings.risk_session_close_buffer_min
            if close_buffer_min < 0:
                close_buffer_hour = 14
                close_buffer_min = 60 + close_buffer_min
            close_with_buffer = time(close_buffer_hour, close_buffer_min)

            if current_time < open_with_delay:
                return (
                    False,
                    f"장 개시 후 안정화 대기 (09:{settings.risk_session_open_delay_min:02d} 이후 허용)",
                    session_info,
                )
            if current_time >= close_with_buffer:
                return (
                    False,
                    f"장 마감 임박 — 신규 진입 차단 ({close_buffer_hour}:{close_buffer_min:02d} 이전까지 허용)",
                    session_info,
                )

            return True, "정규장 거래 허용", session_info

        # CLOSING_AUCTION: block new entries
        if session == MarketSession.CLOSING_AUCTION:
            return (
                False,
                f"{description} — 신규 진입 불가",
                session_info,
            )

        # AFTER_HOURS: block new entries, allow monitoring
        if session == MarketSession.AFTER_HOURS:
            return (
                False,
                f"{description} — 신규 진입 불가 (모니터링만 허용)",
                session_info,
            )

        return False, "알 수 없는 세션 상태", session_info

    # === Stale Data Gate ===

    async def check_price_freshness(self, stock_code: str) -> tuple[bool, float]:
        """Check if latest price data is fresh enough.
        Returns (ok, age_seconds).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT time FROM ohlcv WHERE stock_code = $1 ORDER BY time DESC LIMIT 1",
                stock_code,
            )
        if not row:
            return False, float("inf")

        age = (datetime.now(timezone.utc) - row["time"]).total_seconds()
        ok = age <= settings.risk_stale_price_seconds
        return ok, age

    # === Broker Circuit Breaker ===

    async def record_broker_failure(self):
        """Record a broker API failure. Auto-blocks after N consecutive failures."""
        count = await self.redis.incr(BROKER_FAIL_KEY)
        await self.redis.expire(BROKER_FAIL_KEY, 300)  # 5분 윈도우
        if count >= settings.risk_broker_max_failures:
            await self.activate_kill_switch(
                f"브로커 API 연속 {count}회 실패"
            )

    async def reset_broker_failures(self):
        """Reset broker failure counter after a successful call."""
        await self.redis.delete(BROKER_FAIL_KEY)

    async def get_broker_failure_count(self) -> int:
        val = await self.redis.get(BROKER_FAIL_KEY)
        return int(val) if val else 0

    # === Sector Concentration ===

    async def check_sector_concentration(self, stock_code: str, order_value: float) -> tuple[bool, str]:
        """Check if adding this order would exceed sector concentration limit."""
        async with self.pool.acquire() as conn:
            # Get sector of this stock
            sector_row = await conn.fetchrow(
                "SELECT sector FROM stocks WHERE stock_code = $1", stock_code
            )
            if not sector_row or not sector_row["sector"]:
                return True, ""

            sector = sector_row["sector"]

            # Get total portfolio value
            snap = await conn.fetchrow(
                "SELECT total_value FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
            )
            total_value = float(snap["total_value"]) if snap else settings.initial_capital

            # Get current sector exposure
            sector_exposure = await conn.fetchval(
                """
                SELECT COALESCE(SUM(pp.quantity * pp.current_price), 0)
                FROM portfolio_positions pp
                JOIN stocks s ON pp.stock_code = s.stock_code
                WHERE s.sector = $1 AND pp.quantity > 0
                """,
                sector,
            )

        new_exposure = float(sector_exposure) + order_value
        ratio = new_exposure / total_value if total_value > 0 else 0

        if ratio > settings.risk_max_sector_ratio:
            return False, f"섹터 '{sector}' 집중 한도 초과: {ratio:.1%} > {settings.risk_max_sector_ratio:.0%}"

        return True, ""

    # === Symbol Validation ===

    async def check_symbol_exists(self, stock_code: str) -> tuple[bool, str]:
        """Verify stock_code exists in stocks table."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stock_code, stock_name FROM stocks WHERE stock_code = $1 AND is_active = TRUE",
                stock_code,
            )
        if not row:
            return False, f"종목 '{stock_code}' 미등록 또는 비활성"
        return True, ""

    # === Outlier Price Detection ===

    async def check_price_sanity(self, stock_code: str, order_price: float) -> tuple[bool, str]:
        """Detect outlier prices (>2x or <0.5x vs previous close)."""
        if order_price <= 0:
            return True, ""  # Skip if no price (market order)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
                stock_code,
            )
        if not row or not row["close"]:
            return True, ""  # No prev data to compare
        prev_close = float(row["close"])
        if prev_close <= 0:
            return True, ""
        ratio = order_price / prev_close
        if ratio > 2.0 or ratio < 0.5:
            return False, f"이상 가격: {order_price:,.0f} (전일 종가 {prev_close:,.0f} 대비 {ratio:.1f}배)"
        return True, ""

    # === Participation Rate ===

    async def check_participation_rate(self, stock_code: str, order_value: float) -> tuple[bool, str]:
        """Check order size vs 20-day average daily trading value."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT AVG(value) as avg_value
                FROM ohlcv
                WHERE stock_code = $1 AND interval = '1d'
                  AND time > NOW() - INTERVAL '30 days'
                """,
                stock_code,
            )
        if not row or not row["avg_value"]:
            return True, ""  # No data to check
        avg_value = float(row["avg_value"])
        if avg_value <= 0:
            return True, ""
        participation = order_value / avg_value
        if participation > settings.risk_max_participation_rate:
            return False, f"참여율 초과: {participation:.2%} > {settings.risk_max_participation_rate:.0%} (20일 평균 거래대금 {avg_value:,.0f})"
        return True, ""

    # === Combined Pre-Trade Check ===

    async def pre_trade_check(self, stock_code: str, order_value: float = 0, order_price: float = 0) -> tuple[bool, list[str]]:
        """Run ALL pre-trade safety checks. Returns (allowed, violations)."""
        violations = []

        # 1. Kill switch
        if await self.is_kill_switch_active():
            violations.append("킬 스위치 활성 상태 — 모든 신규 주문 차단")
            return False, violations

        # 2. Symbol validation
        ok, msg = await self.check_symbol_exists(stock_code)
        if not ok:
            violations.append(msg)
            return False, violations

        # 3. Daily loss
        ok, loss_pct = await self.check_daily_loss()
        if not ok:
            violations.append(f"일간 손실 한도 초과: {loss_pct:.2%}")

        # 4. Session guard
        ok, reason, _session_info = self.is_trading_session()
        if not ok:
            violations.append(f"거래 시간 외: {reason}")

        # 5. Stale data
        ok, age = await self.check_price_freshness(stock_code)
        if not ok:
            violations.append(f"시세 데이터 오래됨: {age:.0f}초 (한도: {settings.risk_stale_price_seconds}초)")

        # 6. Outlier price
        if order_price > 0:
            ok, msg = await self.check_price_sanity(stock_code, order_price)
            if not ok:
                violations.append(msg)

        # 7. Broker circuit breaker
        failures = await self.get_broker_failure_count()
        if failures >= settings.risk_broker_max_failures:
            violations.append(f"브로커 연속 실패 {failures}회 — 신규 주문 차단")

        # 8. Sector concentration
        if order_value > 0:
            ok, msg = await self.check_sector_concentration(stock_code, order_value)
            if not ok:
                violations.append(msg)

        # 9. Participation rate
        if order_value > 0:
            ok, msg = await self.check_participation_rate(stock_code, order_value)
            if not ok:
                violations.append(msg)

        # Log guard result to audit
        if violations:
            await log_event(
                self.pool, source="trading_guard", event_type="pre_trade_blocked",
                symbol=stock_code,
                payload={"violations": violations, "order_value": order_value},
            )

        return len(violations) == 0, violations
