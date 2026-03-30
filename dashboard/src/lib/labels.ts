export type Translator = (key: string) => string;

export function eventTypeLabel(eventType: string, t: Translator) {
  const keyMap: Record<string, string> = {
    price_spike: "event.price_spike",
    volume_surge: "event.volume_surge",
    news_cluster: "event.news_cluster",
    disclosure: "event.disclosure",
    sector_sympathy: "event.sector_sympathy",
    tradingview: "event.tradingview",
  };
  return t(keyMap[eventType] || eventType);
}

export function orderStatusLabel(status: string, t: Translator) {
  const keyMap: Record<string, string> = {
    CREATED: "orderStatus.CREATED",
    VALIDATED: "orderStatus.VALIDATED",
    SUBMITTED: "orderStatus.SUBMITTED",
    ACKED: "orderStatus.ACKED",
    PARTIALLY_FILLED: "orderStatus.PARTIALLY_FILLED",
    FILLED: "orderStatus.FILLED",
    CANCELLED: "orderStatus.CANCELLED",
    REJECTED: "orderStatus.REJECTED",
    BLOCKED: "orderStatus.BLOCKED",
    FAILED: "orderStatus.FAILED",
    UNKNOWN: "orderStatus.UNKNOWN",
    EXPIRED: "orderStatus.EXPIRED",
  };
  return t(keyMap[status] || status);
}
