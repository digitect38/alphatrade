/**
 * Event reference lines for Recharts charts.
 *
 * Renders dashed vertical lines at event dates (no labels — labels are in EventPanel).
 * Must be used inside a Recharts chart component (LineChart, ComposedChart, etc.).
 */

import { ReferenceLine } from "recharts";
import { getEventColor, type MarketEvent } from "../../lib/events";

interface ChartPoint {
  time: string;
}

/**
 * Match event date to closest chart data point.
 * Returns the chart point's time string, or null if no match within 5 days.
 */
function matchEventToChart(evt: MarketEvent, chartData: ChartPoint[]): string | null {
  let matchTime: string | null = null;
  let minDist = Infinity;
  const evtMs = new Date(evt.date).getTime();
  for (const d of chartData) {
    const dist = Math.abs(new Date(d.time).getTime() - evtMs);
    if (dist < minDist) {
      minDist = dist;
      matchTime = d.time;
    }
  }
  return matchTime && minDist <= 5 * 86400000 ? matchTime : null;
}

/**
 * Render event reference lines inside a Recharts chart.
 *
 * Usage:
 * ```tsx
 * <LineChart data={chartData}>
 *   ...
 *   <EventLines events={chartLineEvents} chartData={chartData} />
 * </LineChart>
 * ```
 */
export default function EventLines({
  events,
  chartData,
}: {
  events: MarketEvent[];
  chartData: ChartPoint[];
}) {
  return (
    <>
      {events.map((evt) => {
        const matchTime = matchEventToChart(evt, chartData);
        if (!matchTime) return null;
        return (
          <ReferenceLine
            key={`${evt.date}-${evt.label}`}
            x={matchTime}
            stroke={getEventColor(evt.category)}
            strokeDasharray="4 3"
            strokeWidth={1}
            strokeOpacity={0.5}
          />
        );
      })}
    </>
  );
}
