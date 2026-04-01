import { useMemo, useState } from "react";
import { calcCloseDomain } from "../lib/charts/domain";
import { downsample, maxPointsForPeriod } from "../lib/charts/downsample";
import { formatChartDate, tickInterval, wonFormatter, tooltipDateFormatter } from "../lib/charts/format";
import { toNumber } from "../lib/parse";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import type { OHLCVRecord } from "../types";
import { useChartEvents } from "../hooks/useChartEvents";
import { EventPanel } from "./charts";
import { getEventColor } from "../lib/events";

type ChartPoint = { time: string; close: number };

export default function TechnicalChart({
  data, sma20, sma60, periodLabel, t,
}: {
  data: OHLCVRecord[];
  sma20?: number | null;
  sma60?: number | null;
  periodLabel?: string;
  t: (k: string) => string;
}) {
  const allData = useMemo<ChartPoint[]>(() => {
    const src = data.map((d) => ({ time: d.time, close: toNumber(d.close) }));
    return downsample(src, maxPointsForPeriod(periodLabel));
  }, [data, periodLabel]);

  const [rangeStart, setRangeStart] = useState(0);
  const [rangeEnd, setRangeEnd] = useState(100);
  useMemo(() => { setRangeStart(0); setRangeEnd(100); }, [periodLabel]);

  const chartData = useMemo(() => {
    if (rangeStart === 0 && rangeEnd === 100) return allData;
    const startIdx = Math.floor((rangeStart / 100) * allData.length);
    const endIdx = Math.max(startIdx + 2, Math.ceil((rangeEnd / 100) * allData.length));
    return allData.slice(startIdx, endIdx);
  }, [allData, rangeStart, rangeEnd]);

  const extrema = useMemo(() => {
    if (chartData.length < 2) return null;
    const latest = chartData[chartData.length - 1];
    let minI = 0, maxI = 0;
    for (let i = 1; i < chartData.length; i++) {
      if (chartData[i].close < chartData[minI].close) minI = i;
      if (chartData[i].close > chartData[maxI].close) maxI = i;
    }
    if (chartData[minI].close === chartData[maxI].close) return null;
    return { minIdx: minI, maxIdx: maxI, latest };
  }, [chartData]);

  const yDomain = useMemo(() => calcCloseDomain(chartData.map((d) => d.close)), [chartData]);

  const renderDot = (props: any) => {
    if (!extrema) return null;
    const { cx, cy, index } = props;
    if (index !== extrema.maxIdx && index !== extrema.minIdx) return null;
    const isHigh = index === extrema.maxIdx;
    const pt = chartData[index];
    if (!pt) return null;
    const pct = ((pt.close / extrema.latest.close) - 1) * 100;
    const color = isHigh ? "#dc2626" : "#2563eb";
    const label = `${pt.close.toLocaleString()}원 (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`;
    return (
      <g key={`ex-${index}`}>
        <circle cx={cx} cy={cy} r={5} fill={color} stroke="#fff" strokeWidth={2} />
        <text x={cx} y={cy + (isHigh ? -14 : 18)} textAnchor="middle" fill={color} fontSize={11} fontWeight={700}>
          {label}
        </text>
      </g>
    );
  };

  // === Events (shared hook + components) ===
  const [showEvents, setShowEvents] = useState(true);
  const dateRange = useMemo(() => {
    if (allData.length < 2) return { start: "", end: "" };
    return { start: allData[0].time.slice(0, 10), end: allData[allData.length - 1].time.slice(0, 10) };
  }, [allData]);

  const visibleRange = useMemo(() => {
    if (chartData.length < 2) return { start: "", end: "" };
    return { start: chartData[0].time.slice(0, 10), end: chartData[chartData.length - 1].time.slice(0, 10) };
  }, [chartData]);

  const { visibleEvents, chartLineEvents } = useChartEvents({
    startDate: dateRange.start,
    endDate: dateRange.end,
    visibleStart: visibleRange.start,
    visibleEnd: visibleRange.end,
    enabled: showEvents,
  });

  // Pre-compute event line data (x position + color)
  const eventRefLines = useMemo<Array<{ x: string; color: string }>>(() => {
    if (!chartLineEvents.length || !chartData.length) return [];
    const result: Array<{ x: string; color: string }> = [];
    for (const evt of chartLineEvents) {
      let mt: string | null = null;
      let md = Infinity;
      const ems = new Date(evt.date).getTime();
      for (const d of chartData) {
        const dist = Math.abs(new Date(d.time).getTime() - ems);
        if (dist < md) { md = dist; mt = d.time; }
      }
      if (mt && md <= 5 * 86400000) {
        result.push({ x: mt, color: getEventColor(evt.category) });
      }
    }
    return result;
  }, [chartLineEvents, chartData]);

  const isZoomed = rangeStart > 0 || rangeEnd < 100;
  const [fullscreen, setFullscreen] = useState(false);

  return (
    <div className={`card ${fullscreen ? "chart-fullscreen" : ""}`}>
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
          {isZoomed && (
            <button className="btn btn-sm" style={{ fontSize: "11px" }} onClick={() => { setRangeStart(0); setRangeEnd(100); }}>
              Reset Zoom
            </button>
          )}
          <button className="btn btn-sm" style={{ fontSize: "11px" }} onClick={() => setFullscreen((v) => !v)}>
            {fullscreen ? "✕" : "⛶"}
          </button>
        </div>
      </div>

      <div style={{ borderRadius: "8px", flex: fullscreen ? 1 : undefined, minHeight: fullscreen ? 0 : undefined, position: "relative" }}>
        <ResponsiveContainer width="100%" height={fullscreen ? "100%" : 360}>
          <LineChart data={chartData} margin={{ top: 30, right: 16, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
            <XAxis
              dataKey="time" fontSize={11}
              interval={tickInterval(chartData.length)}
              minTickGap={chartData.length <= 40 ? 16 : 28}
              tickFormatter={(v: string) => formatChartDate(v, periodLabel)}
            />
            <YAxis
              fontSize={11} domain={yDomain} tickCount={6}
              tickFormatter={(v: number) => Math.round(v).toLocaleString()}
              width={80}
            />
            <Tooltip
              formatter={(v: number) => wonFormatter(v)}
              labelFormatter={(v: string) => tooltipDateFormatter(v)}
            />
            <Legend />
            <Line
              type="linear" isAnimationActive={false}
              dataKey="close" stroke="var(--color-accent)" strokeWidth={2}
              dot={renderDot as any} connectNulls
              name={t("analysis.currentPrice")}
            />
          </LineChart>
        </ResponsiveContainer>
        {/* Event lines overlay — SVG positioned over the chart area */}
        {showEvents && eventRefLines.length > 0 && chartData.length > 1 && (
          <svg style={{ position: "absolute", top: 0, left: 80, right: 16, bottom: 30, pointerEvents: "none", width: "calc(100% - 96px)", height: "calc(100% - 35px)" }}>
            {eventRefLines.map((evt, i) => {
              const idx = chartData.findIndex((d) => d.time === evt.x);
              if (idx < 0) return null;
              const pct = idx / (chartData.length - 1);
              return (
                <line key={`evl${i}`} x1={`${pct * 100}%`} x2={`${pct * 100}%`} y1="0" y2="100%"
                  stroke={evt.color} strokeDasharray="5 4" strokeWidth={1.2} strokeOpacity={0.7} />
              );
            })}
          </svg>
        )}
      </div>

      {/* Zoom slider */}
      <div className="flex gap-sm items-center" style={{ padding: "8px 0", fontSize: "11px" }}>
        <span className="text-secondary">Zoom:</span>
        <input type="range" min={0} max={Math.max(0, rangeEnd - 5)} value={rangeStart}
          onChange={(e) => setRangeStart(Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--color-accent)" }} />
        <input type="range" min={Math.min(100, rangeStart + 5)} max={100} value={rangeEnd}
          onChange={(e) => setRangeEnd(Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--color-accent)" }} />
        <span className="text-secondary">{chartData.length}pts</span>
      </div>

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
