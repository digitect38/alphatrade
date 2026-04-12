/**
 * Shared formatting utilities — used across ALL pages.
 * NO page should redefine these functions inline.
 */

/** Convert unknown value to number safely. */
export function toNum(value: number | string | undefined): number {
  return typeof value === "number" ? value : Number(value || 0);
}

/** Format number with Korean locale. */
export function formatNumber(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return "0";
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

/** Format with sign prefix (+/-). */
export function formatSigned(value: number | null | undefined, decimals = 2): string {
  if (value == null || isNaN(value)) return "0";
  return `${value > 0 ? "+" : ""}${value.toFixed(decimals)}`;
}

/** Compact number (K, M, B). */
export function formatCompact(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return "0";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return `${value}`;
}

/** Format datetime as Korean locale string. */
export function formatDateTime(value: string | Date): string {
  return new Date(value).toLocaleString("ko-KR");
}

/** Format date only. */
export function formatDate(value: string | Date): string {
  return new Date(value).toLocaleDateString("ko-KR");
}

/** Format time only (HH:MM). */
export function formatTime(value: string | Date): string {
  return new Date(value).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

/** Summarize object details into short string. */
export function summarizeDetails(details: Record<string, unknown>, maxEntries = 3): string {
  const entries = Object.entries(details).slice(0, maxEntries).map(([k, v]) => `${k}: ${String(v)}`);
  return entries.length > 0 ? entries.join(" · ") : "-";
}
