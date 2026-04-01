/**
 * Shared Y-axis domain calculation utilities.
 */

/** Round axis value to human-friendly numbers (5k, 1k, 100, 10 steps). */
export function roundAxis(value: number, dir: "up" | "down"): number {
  const u = value >= 100000 ? 5000 : value >= 10000 ? 1000 : value >= 1000 ? 100 : 10;
  return dir === "up" ? Math.ceil(value / u) * u : Math.max(0, Math.floor(value / u) * u);
}

/** Price domain from close prices — with rounding for clean axis labels. */
export function calcCloseDomain(closes: number[]): [number, number] {
  const valid = closes.filter(Number.isFinite);
  if (!valid.length) return [0, 100];
  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const span = Math.max(max - min, max * 0.02, 1);
  return [roundAxis(min - span * 0.12, "down"), roundAxis(max + span * 0.18, "up")];
}

/** Price domain from OHLC data — tighter padding, no rounding. */
export function calcOHLCDomain(prices: number[]): [number, number] {
  const valid = prices.filter(Number.isFinite);
  if (!valid.length) return [0, 100];
  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const pad = Math.max((max - min) * 0.08, max * 0.01, 100);
  return [Math.max(0, min - pad), max + pad];
}
