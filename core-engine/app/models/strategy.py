from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Strategy Signal ---


class StrategySignalRequest(BaseModel):
    stock_code: str
    interval: str = "1d"


class BatchSignalRequest(BaseModel):
    stock_codes: list[str] | None = None  # None = active universe
    interval: str = "1d"


class StrategyComponent(BaseModel):
    name: str  # momentum, mean_reversion, volume, sentiment
    score: float  # -1.0 ~ 1.0
    weight: float  # 0.0 ~ 1.0


class StrategySignalResult(BaseModel):
    stock_code: str
    signal: Literal["BUY", "SELL", "HOLD"]
    strength: float  # 0.0 ~ 1.0
    ensemble_score: float  # -1.0 ~ 1.0
    components: list[StrategyComponent] = []
    reasons: list[str] = []
    computed_at: datetime


class BatchSignalResult(BaseModel):
    signals: list[StrategySignalResult] = []
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    computed_at: datetime


# --- Backtest ---


class BacktestRequest(BaseModel):
    stock_code: str
    initial_capital: float = 10_000_000  # 1000만원
    strategy: str = "ensemble"  # ensemble, momentum, mean_reversion
    interval: str = "1d"


class BacktestTrade(BaseModel):
    date: str
    action: Literal["BUY", "SELL"]
    price: float
    quantity: int
    pnl: float | None = None
    holding_bars: int | None = None


class BacktestResult(BaseModel):
    stock_code: str
    strategy: str
    initial_capital: float
    final_capital: float
    period_bars: int = 0
    total_return: float  # %
    benchmark_return: float | None = None
    annual_return: float | None = None
    max_drawdown: float  # %
    sharpe_ratio: float | None = None
    win_rate: float  # %
    profit_factor: float | None = None
    avg_trade_pnl: float | None = None
    avg_holding_bars: float | None = None
    max_consecutive_losses: int = 0
    total_trades: int
    trades: list[BacktestTrade] = []
    equity_curve: list[float] = []
    computed_at: datetime


# --- TradingView Webhook ---


class TradingViewWebhook(BaseModel):
    ticker: str
    action: Literal["buy", "sell", "alert"]
    price: float | None = None
    message: str | None = None
    secret: str | None = None  # Webhook authentication
