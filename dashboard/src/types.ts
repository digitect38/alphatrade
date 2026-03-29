export interface HealthStatus {
  status: string;
  db: string;
  redis: string;
}

export interface PositionInfo {
  stock_code: string;
  stock_name: string | null;
  quantity: number;
  avg_price: number;
  current_price: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  weight: number | null;
}

export interface PortfolioStatus {
  total_value: number;
  cash: number;
  invested: number;
  unrealized_pnl: number;
  daily_pnl: number | null;
  total_return_pct: number;
  positions_count: number;
  positions: PositionInfo[];
  updated_at: string;
}

export interface StrategyComponent {
  name: string;
  score: number;
  weight: number;
}

export interface StrategySignal {
  stock_code: string;
  signal: "BUY" | "SELL" | "HOLD";
  strength: number;
  ensemble_score: number;
  components: StrategyComponent[];
  reasons: string[];
  computed_at: string;
}

export interface BatchSignalResult {
  signals: StrategySignal[];
  buy_count: number;
  sell_count: number;
  hold_count: number;
  computed_at: string;
}

export interface OrderHistoryItem {
  order_id: string;
  time: string;
  stock_code: string;
  side: string;
  order_type: string;
  quantity: number;
  price: number | null;
  filled_qty: number;
  filled_price: number | null;
  status: string;
  slippage: number | null;
  commission: number | null;
}

export interface TechnicalIndicators {
  sma_5: number | null;
  sma_20: number | null;
  sma_60: number | null;
  rsi_14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  atr_14: number | null;
  obv: number | null;
  mfi_14: number | null;
}

export interface TechnicalSignal {
  indicator: string;
  signal: "bullish" | "bearish" | "neutral";
  strength: number;
  description: string;
}

export interface TechnicalResult {
  stock_code: string;
  interval: string;
  current_price: number | null;
  indicators: TechnicalIndicators;
  signals: TechnicalSignal[];
  trend_score: number;
  momentum_score: number;
  overall_score: number;
  computed_at: string;
}

export interface OHLCVRecord {
  time: string;
  stock_code: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
