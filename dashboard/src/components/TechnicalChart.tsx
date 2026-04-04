import { useMemo, useState } from "react";
import type { OHLCVRecord } from "../types";
import { useChartEvents } from "../hooks/useChartEvents";
import { EventPanel, LightweightChart } from "./charts";
import type { OHLCVPoint, ChartMarker } from "./charts";
import { getEventColor } from "../lib/events";

export default function TechnicalChart({
  data, sma20, sma60, periodLabel, t,
}: {
  data: OHLCVRecord[];
  sma20?: number | null;
  sma60?: number | null;
  periodLabel?: string;
  t: (k: string) => string;
}) {
  // Convert OHLCVRecord[] to OHLCVPoint[] for LightweightChart
  const chartData = useMemo<OHLCVPoint[]>(() => {
    return data
      .filter((d) => d.close > 0)
      .map((d) => ({
        time: d.time,
        open: Number(d.open) || 0,
        high: Number(d.high) || 0,
        low: Number(d.low) || 0,
        close: Number(d.close),
        volume: Number(d.volume) || 0,
      }));
  }, [data]);

  // === Events ===
  const [showEvents, setShowEvents] = useState(true);
  const dateRange = useMemo(() => {
    if (chartData.length < 2) return { start: "", end: "" };
    return { start: chartData[0].time.slice(0, 10), end: chartData[chartData.length - 1].time.slice(0, 10) };
  }, [chartData]);

  const { visibleEvents, chartLineEvents } = useChartEvents({
    startDate: dateRange.start,
    endDate: dateRange.end,
    visibleStart: dateRange.start,
    visibleEnd: dateRange.end,
    enabled: showEvents,
  });

  // Convert events to LightweightChart markers
  const markers = useMemo<ChartMarker[]>(() => {
    if (!showEvents || !chartLineEvents.length || !chartData.length) return [];
    const result: ChartMarker[] = [];
    for (const evt of chartLineEvents) {
      // Find closest data point
      let closest: string | null = null;
      let minDist = Infinity;
      const ems = new Date(evt.date).getTime();
      for (const d of chartData) {
        const dist = Math.abs(new Date(d.time).getTime() - ems);
        if (dist < minDist) { minDist = dist; closest = d.time; }
      }
      if (closest && minDist <= 5 * 86400000) {
        result.push({ time: closest, color: getEventColor(evt.category), label: evt.label });
      }
    }
    return result;
  }, [chartLineEvents, chartData, showEvents]);

  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{t("analysis.priceChart")}</h3>
        <div className="flex gap-sm items-center">
          {periodLabel && <span className="text-secondary">{t("analysis.period")}: {periodLabel}</span>}
          <button
            className={`btn btn-sm ${showEvents ? "btn-primary" : ""}`}
            style={{ fontSize: "11px" }}
            onClick={() => setShowEvents((v) => !v)}
          >
            {t("analysis.events")} {showEvents ? "ON" : "OFF"}
          </button>
        </div>
      </div>

      <LightweightChart
        data={chartData}
        mode="line"
        volume={true}
        markers={markers}
        height={400}
        showMA20={true}
        showMA50={true}
      />

      {(sma20 || sma60) && (
        <div className="flex gap-xl text-secondary" style={{ marginTop: "4px", fontSize: "12px" }}>
          {sma20 && <span>SMA20: {sma20.toLocaleString()}</span>}
          {sma60 && <span>SMA60: {sma60.toLocaleString()}</span>}
        </div>
      )}

      {/* Event panel (shared component) */}
      {showEvents && <EventPanel events={visibleEvents} t={t} />}
    </div>
  );
}
