/**
 * Event reference lines for Recharts charts.
 *
 * Returns an array of ReferenceLine elements (not a wrapper component),
 * because Recharts only recognizes direct children, not nested fragments.
 *
 * Usage inside a chart:
 *   {renderEventLines(chartLineEvents, chartData)}
 */

import React from "react";
import { ReferenceLine } from "recharts";
import { getEventColor, type MarketEvent } from "../../lib/events";

interface ChartPoint {
  time: string;
}

function matchEventToChart(evt: MarketEvent, chartData: ChartPoint[]): string | null {
  let matchTime: string | null = null;
  let minDist = Infinity;
  const evtMs = new Date(evt.date).getTime();
  for (const d of chartData) {
    const dist = Math.abs(new Date(d.time).getTime() - evtMs);
    if (dist < minDist) { minDist = dist; matchTime = d.time; }
  }
  return matchTime && minDist <= 5 * 86400000 ? matchTime : null;
}

/**
 * Render event reference lines. Call this directly inside a Recharts chart:
 *
 * ```tsx
 * <LineChart data={chartData}>
 *   {renderEventLines(events, chartData)}
 * </LineChart>
 * ```
 */
export function renderEventLines(
  events: MarketEvent[],
  chartData: ChartPoint[],
): (React.ReactElement | null)[] {
  const lines: React.ReactElement[] = [];
  for (const evt of events) {
    const matchTime = matchEventToChart(evt, chartData);
    if (!matchTime) continue;
    lines.push(
      <ReferenceLine
        key={`evt-${evt.date}-${evt.label}`}
        x={matchTime}
        stroke={getEventColor(evt.category)}
        strokeDasharray="5 4"
        strokeWidth={1.2}
        strokeOpacity={0.7}
      />
    );
  }
  return lines;
}

// Keep default export for backward compat, but prefer renderEventLines
export default function EventLines({
  events, chartData,
}: { events: MarketEvent[]; chartData: ChartPoint[] }) {
  return <>{renderEventLines(events, chartData)}</>;
}
