import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from app.config import settings
from app.models.execution import RiskCheckRequest, RiskCheckResult
from app.services.audit import log_event

logger = logging.getLogger(__name__)


class RiskManager:
    @property
    def MAX_TOTAL_CAPITAL(self):
        return settings.risk_max_total_capital

    @property
    def MAX_PER_STOCK(self):
        return settings.risk_max_per_stock

    @property
    def MAX_POSITION_RATIO(self):
        return settings.risk_max_position_ratio

    @property
    def MAX_TOTAL_INVESTED(self):
        return settings.risk_max_total_invested

    @property
    def STOP_LOSS_PCT(self):
        return settings.risk_stop_loss_pct

    @property
    def TAKE_PROFIT_PCT(self):
        return settings.risk_take_profit_pct

    @property
    def MAX_DAILY_LOSS_PCT(self):
        return settings.risk_max_daily_loss_pct

    @property
    def MAX_DAILY_TRADES(self):
        return settings.risk_max_daily_trades

    async def check_order(self, request: RiskCheckRequest, portfolio_value: float, cash: float, *, pool: asyncpg.Pool) -> RiskCheckResult:
        """Pre-trade risk check."""
        violations = []
        warnings = []

        price = request.price or await self._get_last_price(request.stock_code, pool=pool)
        if not price:
            return RiskCheckResult(allowed=False, violations=["현재가를 조회할 수 없습니다"])

        order_cost = price * request.quantity

        if request.side == "BUY":
            await self._check_buy_limits(request, order_cost, portfolio_value, cash, pool, violations, warnings)
        elif request.side == "SELL":
            await self._check_sell_limits(request, pool, violations)

        await self._check_daily_limits(portfolio_value, pool, violations)

        max_qty = None
        if request.side == "BUY" and price > 0:
            available = min(cash, portfolio_value * self.MAX_POSITION_RATIO) if portfolio_value > 0 else cash
            max_qty = int(available / price)

        result = RiskCheckResult(
            allowed=len(violations) == 0,
            violations=violations, warnings=warnings, max_quantity=max_qty,
        )

        # Audit log for risk decisions (v1.31 A-6)
        if not result.allowed:
            await log_event(
                pool, source="risk", event_type="risk_rejected",
                symbol=request.stock_code,
                payload={"side": request.side, "qty": request.quantity,
                         "violations": violations, "warnings": warnings},
            )

        return result

    async def _check_buy_limits(self, request, order_cost, portfolio_value, cash, pool, violations, warnings):
        """BUY-side risk checks: per-stock, total capital, cash, concentration, invested ratio."""
        if order_cost > self.MAX_PER_STOCK:
            violations.append(f"종목당 한도 초과: {order_cost:,.0f}원 > {self.MAX_PER_STOCK:,.0f}원")

        async with pool.acquire() as conn:
            total_invested = await conn.fetchval(
                "SELECT COALESCE(SUM(quantity * avg_price), 0) FROM portfolio_positions WHERE quantity > 0"
            )
        if float(total_invested) + order_cost > self.MAX_TOTAL_CAPITAL:
            violations.append(f"총 투자 한도 초과: 현재 {float(total_invested):,.0f}원 + 주문 {order_cost:,.0f}원 > {self.MAX_TOTAL_CAPITAL:,.0f}원")

        if order_cost > cash:
            violations.append(f"잔고 부족: 필요 {order_cost:,.0f}원, 보유 {cash:,.0f}원")

        if portfolio_value > 0:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT quantity, avg_price FROM portfolio_positions WHERE stock_code = $1",
                    request.stock_code,
                )
            existing_value = float(row["quantity"]) * float(row["avg_price"]) if row else 0
            ratio = (existing_value + order_cost) / portfolio_value
            if ratio > self.MAX_POSITION_RATIO:
                violations.append(f"종목 비중 초과: {ratio:.1%} > {self.MAX_POSITION_RATIO:.0%}")
            elif ratio > self.MAX_POSITION_RATIO * 0.8:
                warnings.append(f"종목 비중 경고: {ratio:.1%}")

            invested_ratio = (portfolio_value - cash + order_cost) / portfolio_value
            if invested_ratio > self.MAX_TOTAL_INVESTED:
                violations.append(f"총 투자 비율 초과: {invested_ratio:.1%} > {self.MAX_TOTAL_INVESTED:.0%}")

    async def _check_sell_limits(self, request, pool, violations):
        """SELL-side risk checks: sufficient shares."""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT quantity FROM portfolio_positions WHERE stock_code = $1", request.stock_code,
            )
        held = row["quantity"] if row else 0
        if request.quantity > held:
            violations.append(f"보유 수량 부족: 요청 {request.quantity}주, 보유 {held}주")

    async def _check_daily_limits(self, portfolio_value, pool, violations):
        """Daily trade count and loss limits."""
        async with pool.acquire() as conn:
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
            count = await conn.fetchval("SELECT count(*) FROM orders WHERE time >= $1", today_start)
        if count >= self.MAX_DAILY_TRADES:
            violations.append(f"일간 거래 횟수 초과: {count} >= {self.MAX_DAILY_TRADES}")

        daily_loss = await self._get_daily_pnl(pool=pool)
        if daily_loss is not None and portfolio_value > 0:
            daily_loss_pct = daily_loss / portfolio_value
            if daily_loss_pct <= self.MAX_DAILY_LOSS_PCT:
                violations.append(f"일간 손실 한도 초과: {daily_loss_pct:.2%} <= {self.MAX_DAILY_LOSS_PCT:.0%}")

    async def check_stop_loss(self, stock_code: str, avg_price: float, current_price: float) -> bool:
        """Check if stop-loss should trigger."""
        if avg_price <= 0:
            return False
        pnl_pct = (current_price - avg_price) / avg_price
        return pnl_pct <= self.STOP_LOSS_PCT

    async def check_take_profit(self, stock_code: str, avg_price: float, current_price: float) -> bool:
        """Check if take-profit should trigger."""
        if avg_price <= 0:
            return False
        pnl_pct = (current_price - avg_price) / avg_price
        return pnl_pct >= self.TAKE_PROFIT_PCT

    async def _get_last_price(self, stock_code: str, *, pool: asyncpg.Pool) -> float | None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT close FROM ohlcv WHERE stock_code = $1 ORDER BY time DESC LIMIT 1",
                stock_code,
            )
        return float(row["close"]) if row else None

    async def _get_daily_pnl(self, *, pool: asyncpg.Pool) -> float | None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT daily_pnl FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
            )
        return float(row["daily_pnl"]) if row and row["daily_pnl"] else None
