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
    # Phase 1 fields
    start_date: str | None = None        # "YYYY-MM-DD", None = use all data
    end_date: str | None = None          # "YYYY-MM-DD", None = latest
    buy_fee_rate: float = 0.00015
    sell_fee_rate: float = 0.00015
    sell_tax_rate: float = 0.0018
    slippage_rate: float = 0.0005
    capital_fraction: float = 0.85
    max_drawdown_stop: float = 0.08
    benchmark: str = "buy_and_hold"       # "buy_and_hold" | "kospi" | "none"


class BacktestTrade(BaseModel):
    date: str
    action: Literal["BUY", "SELL"]
    price: float
    quantity: int
    pnl: float | None = None
    holding_bars: int | None = None
    reason: str | None = None             # e.g. "sma_golden_cross", "rsi_oversold"


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
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    win_rate: float  # %
    profit_factor: float | None = None
    avg_trade_pnl: float | None = None
    avg_holding_bars: float | None = None
    max_consecutive_losses: int = 0
    total_trades: int
    expectancy: float | None = None       # avg_win * win_rate - avg_loss * loss_rate
    exposure_pct: float | None = None     # % of bars with position
    statistical_warnings: list[str] = []   # warnings about result reliability
    trades: list[BacktestTrade] = []
    equity_curve: list[float] = []        # kept for backward compat
    equity_series: list[dict] | None = None   # [{time, equity, benchmark, drawdown}]
    trade_markers: list[dict] | None = None   # [{time, action, price}]
    monthly_returns: list[dict] | None = None # [{month, return_pct}]
    computed_at: datetime
    start_date: str | None = None
    end_date: str | None = None
    interval: str = "1d"


# --- TradingView Webhook ---


class TradingViewWebhook(BaseModel):
    ticker: str
    action: Literal["buy", "sell", "alert"]
    price: float | None = None
    message: str | None = None
    secret: str | None = None  # Webhook authentication
