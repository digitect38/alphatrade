/**
 * Shared chart formatting utilities.
 */

/** Format number as Korean Won. */
export const wonFormatter = (v: number) => `${Number(v).toLocaleString()}원`;

/** Format number with sign prefix. */
export const signedFormatter = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}`;

/** Format as percentage. */
export const pctFormatter = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

/** Format date for chart label based on period. */
export function formatChartDate(value: string, period?: string): string {
  const d = new Date(value);
  // Intraday: show time (HH:MM)
  if (["1m", "10m", "1H", "1D"].includes(period || ""))
    return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  // Long-term: year + month
  if (["1Y", "3Y", "5Y", "10Y", "ALL"].includes(period || ""))
    return d.toLocaleDateString("ko-KR", { year: "2-digit", month: "short" });
  // Default: month + day
  return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

/** Format date for tooltip. */
export const tooltipDateFormatter = (v: string) =>
  new Date(v).toLocaleString("ko-KR");

/** Format price for Y-axis label (k suffix). */
export function priceAxisFormatter(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
  return `${v}`;
}

/** Smart tick interval based on data length. */
export function tickInterval(len: number): number | "preserveEnd" {
  if (len <= 30) return "preserveEnd";
  if (len <= 80) return 8;
  if (len <= 140) return 16;
  return 24;
}
