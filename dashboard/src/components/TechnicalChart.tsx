import { useMemo, useState } from "react";
import type { OHLCVRecord } from "../types";
import { useChartEvents } from "../hooks/useChartEvents";
import { EventPanel, LightweightChart } from "./charts";
import type { OHLCVPoint, ChartMarker } from "./charts";
import { getEventColor } from "../lib/events";

export default function TechnicalChart({
  data, sma20, sma60, periodLabel, t, interval,
}: {
  data: OHLCVRecord[];
  sma20?: number | null;
  sma60?: number | null;
  periodLabel?: string;
  t: (k: string) => string;
  interval?: string;
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

  const [chartMode, setChartMode] = useState<"candle" | "line">("line");
  const [showMa20, setShowMa20] = useState(true);
  const [showMa50, setShowMa50] = useState(true);
  const [showEvents, setShowEvents] = useState(true);
  const [showRsi, setShowRsi] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const isIntraday = interval === "1m";
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
        // Keep on-chart markers compact; full event text is shown in EventPanel below.
        result.push({ time: closest, color: getEventColor(evt.category), label: "" });
      }
    }
    return result;
  }, [chartLineEvents, chartData, showEvents]);

  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{t("analysis.priceChart")}</h3>
        <div className="flex gap-sm items-center" style={{ flexWrap: "wrap" }}>
          {periodLabel && <span className="text-secondary">{t("analysis.period")}: {periodLabel}</span>}
          <button className={`btn btn-sm ${chartMode === "line" ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setChartMode("line")}>Line</button>
          <button className={`btn btn-sm ${chartMode === "candle" ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setChartMode("candle")}>Candle</button>
          <button className={`btn btn-sm ${showMa20 ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setShowMa20(v => !v)}>MA20</button>
          <button className={`btn btn-sm ${showMa50 ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setShowMa50(v => !v)}>MA50</button>
          <button className={`btn btn-sm ${showRsi ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setShowRsi(v => !v)}>RSI</button>
          <button className={`btn btn-sm ${showMacd ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setShowMacd(v => !v)}>MACD</button>
          <button className={`btn btn-sm ${showEvents ? "btn-primary" : ""}`} style={{ fontSize: "11px" }} onClick={() => setShowEvents(v => !v)}>{t("analysis.events")}</button>
        </div>
      </div>

      <LightweightChart
        data={chartData}
        mode={chartMode}
        volume={true}
        markers={markers}
        height={440}
        showMA20={showMa20}
        showMA50={showMa50}
        showRSI={showRsi}
        showMACD={showMacd}
        intraday={isIntraday}
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
