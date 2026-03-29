from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Order ---


class OrderRequest(BaseModel):
    stock_code: str
    side: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    price: float | None = None  # Required for LIMIT orders
    signal_id: str | None = None  # Reference to strategy signal


class OrderResult(BaseModel):
    order_id: str
    stock_code: str
    side: str
    order_type: str
    quantity: int
    price: float | None = None
    filled_qty: int = 0
    filled_price: float | None = None
    status: str  # PENDING, SUBMITTED, FILLED, PARTIAL, CANCELLED, FAILED
    risk_checks: list[str] = []
    message: str = ""
    created_at: datetime


class OrderHistoryItem(BaseModel):
    order_id: str
    time: datetime
    stock_code: str
    side: str
    order_type: str
    quantity: int
    price: float | None
    filled_qty: int
    filled_price: float | None
    status: str
    slippage: float | None
    commission: float | None


# --- Portfolio ---


class PositionInfo(BaseModel):
    stock_code: str
    stock_name: str | None = None
    quantity: int
    avg_price: float
    current_price: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    weight: float | None = None


class PortfolioStatus(BaseModel):
    total_value: float  # 총 평가금액
    cash: float
    invested: float  # 투자 원금
    unrealized_pnl: float  # 미실현 손익
    daily_pnl: float | None = None
    total_return_pct: float  # 총 수익률 %
    positions_count: int
    positions: list[PositionInfo] = []
    updated_at: datetime


# --- Risk ---


class RiskCheckRequest(BaseModel):
    stock_code: str
    side: Literal["BUY", "SELL"]
    quantity: int
    price: float | None = None


class RiskCheckResult(BaseModel):
    allowed: bool
    violations: list[str] = []
    warnings: list[str] = []
    max_quantity: int | None = None  # Maximum allowed quantity
