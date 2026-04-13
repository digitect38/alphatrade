/**
 * Asset detail page helper functions — chart computations and formatting.
 * Extracted from AssetDetail.tsx to reduce file size.
 */

import type { RangeKey, AssetChartPoint } from "./types";

export function formatChartLabel(value: string, range: RangeKey, interval = "1d") {
  const date = new Date(value);
  if (["1m", "10m", "1H", "1D", "5D"].includes(range) && interval === "1m") {
    return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

export function computeMovingAverage(data: AssetChartPoint[], period: number) {
  return data.map((_, index) => {
    if (index + 1 < period) return null;
    const slice = data.slice(index + 1 - period, index + 1);
    const total = slice.reduce((sum, item) => sum + item.close, 0);
    return Number((total / period).toFixed(2));
  });
}

export function normalizeSeries(data: AssetChartPoint[]) {
  const base = data[0]?.close ?? 0;
  if (!base) return data.map(() => null);
  return data.map((item) => Number((((item.close / base) - 1) * 100).toFixed(2)));
}

export function computeRsi(data: AssetChartPoint[], period: number) {
  if (data.length < period + 1) return data.map(() => null);
  const closes = data.map((item) => item.close);
  const result = Array<number | null>(data.length).fill(null);
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1];
    if (delta >= 0) avgGain += delta;
    else avgLoss += Math.abs(delta);
  }
  avgGain /= period;
  avgLoss /= period;
  result[period] = avgLoss === 0 ? 100 : Number((100 - (100 / (1 + avgGain / avgLoss))).toFixed(2));
  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    const gain = Math.max(delta, 0);
    const loss = Math.max(-delta, 0);
    avgGain = ((avgGain * (period - 1)) + gain) / period;
    avgLoss = ((avgLoss * (period - 1)) + loss) / period;
    result[i] = avgLoss === 0 ? 100 : Number((100 - (100 / (1 + avgGain / avgLoss))).toFixed(2));
  }
  return result;
}

export function computeEma(values: number[], period: number, mask?: Array<number | null>) {
  const result = Array<number | null>(values.length).fill(null);
  const multiplier = 2 / (period + 1);
  let previous: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (mask && mask[i] == null) { result[i] = null; continue; }
    if (previous == null) { previous = values[i]; result[i] = Number(previous.toFixed(2)); continue; }
    previous = ((values[i] - previous) * multiplier) + previous;
    result[i] = Number(previous.toFixed(2));
  }
  return result;
}

export function computeMacd(data: AssetChartPoint[]) {
  const closes = data.map((item) => item.close);
  const ema12 = computeEma(closes, 12);
  const ema26 = computeEma(closes, 26);
  const macd = closes.map((_, index) => {
    if (ema12[index] == null || ema26[index] == null) return null;
    return Number((ema12[index]! - ema26[index]!).toFixed(2));
  });
  const signal = computeEma(macd.map((value) => value ?? 0), 9, macd);
  const histogram = macd.map((value, index) => {
    if (value == null || signal[index] == null) return null;
    return Number((value - signal[index]!).toFixed(2));
  });
  return { macd, signal, histogram };
}
