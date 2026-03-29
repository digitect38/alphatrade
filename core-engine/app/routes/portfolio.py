import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import get_db
from app.models.execution import PortfolioStatus, PositionInfo

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_position_info(p) -> tuple[PositionInfo, float, float]:
    """Build PositionInfo from DB row. Returns (info, invested, unrealized)."""
    qty = p["quantity"]
    avg = float(p["avg_price"])
    current = float(p["current_price"]) if p["current_price"] else avg
    invested = qty * avg
    unrealized = qty * current - invested
    pnl_pct = (current / avg - 1) * 100 if avg > 0 else 0

    info = PositionInfo(
        stock_code=p["stock_code"], stock_name=p["stock_name"],
        quantity=qty, avg_price=avg, current_price=current,
        unrealized_pnl=round(unrealized, 0), unrealized_pnl_pct=round(pnl_pct, 2),
    )
    return info, invested, unrealized


def _apply_weights(position_list: list[PositionInfo], total_value: float):
    """Calculate portfolio weight for each position."""
    for pos in position_list:
        if total_value > 0 and pos.current_price:
            pos.weight = round(pos.quantity * pos.current_price / total_value, 4)


@router.get("/status", response_model=PortfolioStatus)
async def api_portfolio_status(pool: asyncpg.Pool = Depends(get_db)):
    """Get current portfolio status."""
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """SELECT pp.stock_code, pp.quantity, pp.avg_price, pp.current_price, s.stock_name
            FROM portfolio_positions pp LEFT JOIN stocks s ON pp.stock_code = s.stock_code
            WHERE pp.quantity > 0"""
        )
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )

    initial_capital = settings.initial_capital
    cash = float(snapshot["cash"]) if snapshot else initial_capital

    position_list = []
    total_invested = total_unrealized = 0.0
    for p in positions:
        info, invested, unrealized = _build_position_info(p)
        position_list.append(info)
        total_invested += invested
        total_unrealized += unrealized

    total_value = cash + total_invested + total_unrealized
    _apply_weights(position_list, total_value)

    return PortfolioStatus(
        total_value=round(total_value, 0), cash=round(cash, 0),
        invested=round(total_invested, 0), unrealized_pnl=round(total_unrealized, 0),
        total_return_pct=round((total_value / initial_capital - 1) * 100, 2),
        positions_count=len(position_list), positions=position_list, updated_at=now,
    )


@router.get("/positions", response_model=list[PositionInfo])
async def api_portfolio_positions(pool: asyncpg.Pool = Depends(get_db)):
    """Get current positions detail."""
    status = await api_portfolio_status(pool)
    return status.positions
