"""Trading guard — kill switch, session guard, stale data gate, broker circuit breaker.

Central safety layer that must be checked BEFORE any order submission.
All guards are fail-safe: if state is unknown, trading is blocked.
"""

import logging
from datetime import datetime, time, timezone, timedelta

import asyncpg
import redis.asyncio as aioredis

from app.config import settings

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

    async def activate_kill_switch(self, reason: str):
        """Activate kill switch — blocks ALL new orders."""
        await self.redis.set(KILL_SWITCH_KEY, "active")
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    async def deactivate_kill_switch(self):
        """Deactivate kill switch — requires manual operator action."""
        await self.redis.delete(KILL_SWITCH_KEY)
        logger.warning("Kill switch deactivated by operator")

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

    def is_trading_session(self) -> tuple[bool, str]:
        """Check if current time is within allowed trading session.
        KST 09:05 ~ 15:10 (장 개시 5분 후 ~ 마감 20분 전)
        """
        now_kst = datetime.now(timezone(timedelta(hours=9)))
        current_time = now_kst.time()
        weekday = now_kst.weekday()

        # Weekend
        if weekday >= 5:
            return False, "주말 (장 휴무)"

        open_time = time(9, settings.risk_session_open_delay_min)
        close_time = time(15, 30 - settings.risk_session_close_buffer_min)

        if current_time < open_time:
            return False, f"장 개시 대기 (09:{settings.risk_session_open_delay_min:02d} 이후 허용)"
        if current_time > close_time:
            return False, f"장 마감 임박 (15:{30 - settings.risk_session_close_buffer_min:02d} 이전까지 허용)"

        return True, "정상 거래 시간"

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

    # === Combined Pre-Trade Check ===

    async def pre_trade_check(self, stock_code: str, order_value: float = 0) -> tuple[bool, list[str]]:
        """Run ALL pre-trade safety checks. Returns (allowed, violations)."""
        violations = []

        # 1. Kill switch
        if await self.is_kill_switch_active():
            violations.append("킬 스위치 활성 상태 — 모든 신규 주문 차단")
            return False, violations

        # 2. Daily loss
        ok, loss_pct = await self.check_daily_loss()
        if not ok:
            violations.append(f"일간 손실 한도 초과: {loss_pct:.2%}")

        # 3. Session guard
        ok, reason = self.is_trading_session()
        if not ok:
            violations.append(f"거래 시간 외: {reason}")

        # 4. Stale data
        ok, age = await self.check_price_freshness(stock_code)
        if not ok:
            violations.append(f"시세 데이터 오래됨: {age:.0f}초 (한도: {settings.risk_stale_price_seconds}초)")

        # 5. Broker circuit breaker
        failures = await self.get_broker_failure_count()
        if failures >= settings.risk_broker_max_failures:
            violations.append(f"브로커 연속 실패 {failures}회 — 신규 주문 차단")

        # 6. Sector concentration
        if order_value > 0:
            ok, msg = await self.check_sector_concentration(stock_code, order_value)
            if not ok:
                violations.append(msg)

        return len(violations) == 0, violations
