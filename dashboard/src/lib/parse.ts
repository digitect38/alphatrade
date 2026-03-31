/**
 * Safe numeric parsing for API responses.
 *
 * The backend returns Decimal fields as strings ("176300.00").
 * TypeScript interfaces declare them as `number`, but at runtime
 * they are strings. This module provides a single place to handle
 * the conversion so every consumer gets real numbers.
 */

import type { OHLCVRecord } from "../types";

/** Convert any value to a finite number, defaulting to 0. */
export function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** Parse a raw OHLCV record from the API into properly typed numbers. */
export function parseOHLCV(raw: Record<string, unknown>): OHLCVRecord {
  return {
    time: String(raw.time ?? ""),
    stock_code: String(raw.stock_code ?? ""),
    open: toNumber(raw.open),
    high: toNumber(raw.high),
    low: toNumber(raw.low),
    close: toNumber(raw.close),
    volume: toNumber(raw.volume),
  };
}

/** Parse an array of raw OHLCV records. */
export function parseOHLCVList(rawList: Record<string, unknown>[]): OHLCVRecord[] {
  return rawList.map(parseOHLCV);
}
