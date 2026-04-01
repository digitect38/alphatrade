/**
 * Hook for fetching and managing chart events.
 *
 * Fetches from DB API + merges local static events.
 * Filters to visible date range and limits chart lines by importance.
 */

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "./useApi";
import { filterEvents as filterLocalEvents, type MarketEvent } from "../lib/events";

const MAX_CHART_LINES = 12;

interface UseChartEventsOptions {
  /** Full data date range (not zoom range) — used for API fetch */
  startDate: string;
  endDate: string;
  /** Current visible date range (after zoom) */
  visibleStart?: string;
  visibleEnd?: string;
  /** Whether events are enabled */
  enabled: boolean;
}

interface UseChartEventsResult {
  /** All events in the full date range */
  allEvents: MarketEvent[];
  /** Events in the visible (zoomed) range */
  visibleEvents: MarketEvent[];
  /** Top events for chart reference lines (limited count, sorted by importance) */
  chartLineEvents: MarketEvent[];
  /** Loading state */
  loading: boolean;
}

export function useChartEvents({
  startDate,
  endDate,
  visibleStart,
  visibleEnd,
  enabled,
}: UseChartEventsOptions): UseChartEventsResult {
  const [dbEvents, setDbEvents] = useState<MarketEvent[]>([]);
  const [loading, setLoading] = useState(false);

  // Fetch from API only when date range changes (NOT on zoom)
  useEffect(() => {
    if (!enabled || !startDate || !endDate) return;
    setLoading(true);
    apiGet<{ events: MarketEvent[] }>(
      `/events/range?start_date=${startDate}&end_date=${endDate}&min_importance=2`
    )
      .then((d) => setDbEvents(d.events || []))
      .catch(() => setDbEvents([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate, enabled]);

  // Merge DB + local, deduplicate
  const allEvents = useMemo<MarketEvent[]>(() => {
    if (!enabled || !startDate || !endDate) return [];
    const local = filterLocalEvents(startDate, endDate);
    const merged = new Map<string, MarketEvent>();
    for (const e of local) merged.set(`${e.date}|${e.label}`, e);
    for (const e of dbEvents) merged.set(`${e.date}|${e.label}`, e);
    return [...merged.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [startDate, endDate, enabled, dbEvents]);

  // Filter to visible (zoom) range
  const visibleEvents = useMemo<MarketEvent[]>(() => {
    if (!enabled) return [];
    const vs = visibleStart || startDate;
    const ve = visibleEnd || endDate;
    if (!vs || !ve) return allEvents;
    return allEvents.filter((e) => e.date >= vs && e.date <= ve);
  }, [allEvents, visibleStart, visibleEnd, enabled, startDate, endDate]);

  // Top events for chart lines (limited, sorted by importance)
  const chartLineEvents = useMemo(() => {
    if (visibleEvents.length <= MAX_CHART_LINES) return visibleEvents;
    return [...visibleEvents]
      .sort((a, b) => (b.importance ?? 3) - (a.importance ?? 3))
      .slice(0, MAX_CHART_LINES)
      .sort((a, b) => a.date.localeCompare(b.date));
  }, [visibleEvents]);

  return { allEvents, visibleEvents, chartLineEvents, loading };
}
