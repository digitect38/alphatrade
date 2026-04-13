/** Shared types for asset detail page. */

export type RangeKey = "1m" | "10m" | "1H" | "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "3Y" | "5Y" | "10Y" | "MAX";
export type ChartMode = "line" | "candles";

export interface AssetChartPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface AssetOverview {
  stock_code: string;
  stock_name: string;
  market: string;
  sector: string;
  current_price: number;
  change: number;
  change_pct: number;
  volume: number;
  updated_at: string | null;
  session: { current_session: string; description: string; kst_time: string };
}

export interface AssetChartResponse {
  stock_code: string;
  range: RangeKey;
  interval: string;
  data_quality?: "true_ohlc" | "snapshot";
  points: AssetChartPoint[];
}
