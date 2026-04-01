/**
 * Data downsampling for large datasets.
 */

/** Downsample time-series data by picking evenly spaced points. */
export function downsample<T extends { close: number; time: string }>(data: T[], max: number): T[] {
  if (data.length <= max) return data;
  const step = data.length / max;
  const result: T[] = [];
  for (let i = 0; i < max; i++) {
    result.push(data[Math.min(Math.round(i * step), data.length - 1)]);
  }
  if (result[result.length - 1] !== data[data.length - 1]) {
    result.push(data[data.length - 1]);
  }
  return result;
}

/** Max data points based on period label. */
export function maxPointsForPeriod(period?: string): number {
  const m: Record<string, number> = {
    "1m": 120, "10m": 120, "1H": 120, "1D": 120, "1W": 120,
    "1M": 120, "3M": 140, "6M": 150, "1Y": 160,
    "3Y": 180, "5Y": 200, "10Y": 220, "ALL": 220,
  };
  return m[period || ""] || 120;
}

/** Compute simple moving average. */
export function computeMA(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i + 1 < period) return null;
    const slice = closes.slice(i + 1 - period, i + 1);
    return Number((slice.reduce((a, b) => a + b, 0) / period).toFixed(2));
  });
}
