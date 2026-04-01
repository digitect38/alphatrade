/**
 * Shared order/execution status constants, color mappings, and tone functions.
 * Single source of truth for all status-related logic.
 */

export type BadgeTone = "success" | "danger" | "warning" | "info" | "neutral";

export const EXECUTION_ISSUE_STATUSES = new Set(["REJECTED", "BLOCKED", "FAILED", "UNKNOWN"]);
export const EXECUTION_ACTIVE_STATUSES = new Set(["SUBMITTED", "ACKED", "PARTIALLY_FILLED", "FILLED"]);

export const STATUS_COLORS: Record<string, string> = {
  CREATED: "text-neutral",
  VALIDATED: "text-neutral",
  SUBMITTED: "text-warning",
  ACKED: "text-warning",
  PARTIALLY_FILLED: "text-warning",
  FILLED: "text-profit",
  CANCELLED: "text-secondary",
  REJECTED: "text-loss",
  BLOCKED: "text-loss",
  FAILED: "text-loss",
  UNKNOWN: "text-loss",
  EXPIRED: "text-secondary",
};

export const STATUS_BADGES: Record<string, string> = {
  FILLED: "✅", PARTIALLY_FILLED: "⏳", SUBMITTED: "📤", ACKED: "📥",
  REJECTED: "❌", BLOCKED: "🚫", FAILED: "💥", UNKNOWN: "❓",
  CANCELLED: "🚪", EXPIRED: "⏰", CREATED: "📝", VALIDATED: "✔️",
};

export function toneForOrder(status: string): BadgeTone {
  if (status === "FILLED") return "success";
  if (EXECUTION_ISSUE_STATUSES.has(status)) return "danger";
  if (EXECUTION_ACTIVE_STATUSES.has(status)) return "info";
  return "neutral";
}

export type CandidateLane = "eligible" | "blocked" | "watching" | "executed";

export function toneForLane(lane: CandidateLane): BadgeTone {
  if (lane === "eligible") return "success";
  if (lane === "blocked") return "warning";
  if (lane === "executed") return "info";
  return "neutral";
}

/** Direction-based tone. */
export function toneForValue(value: number): BadgeTone {
  if (value > 0) return "success";
  if (value < 0) return "danger";
  return "neutral";
}
