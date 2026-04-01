import { useEffect, useMemo, useState } from "react";
import { calcCloseDomain } from "../lib/charts/domain";
import { downsample, maxPointsForPeriod } from "../lib/charts/downsample";
import { formatChartDate, tickInterval, wonFormatter, tooltipDateFormatter } from "../lib/charts/format";
import { toNumber } from "../lib/parse";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts";
import { apiGet } from "../hooks/useApi";
import type { OHLCVRecord } from "../types";
import { getEventColor, type MarketEvent, filterEvents as filterLocalEvents } from "../lib/events";

type ChartPoint = { time: string; close: number };

// Max events to show lines on chart (prevents clutter)
const MAX_CHART_LINES = 12;

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

  // === Events: fetch once per period change (NOT on zoom) ===
  const [showEvents, setShowEvents] = useState(true);
  const [dbEvents, setDbEvents] = useState<MarketEvent[]>([]);
  const [eventsExpanded, setEventsExpanded] = useState(false);

  // Stable date range from allData (not chartData which changes on zoom)
  const dateRange = useMemo(() => {
    if (allData.length < 2) return null;
    return { start: allData[0].time.slice(0, 10), end: allData[allData.length - 1].time.slice(0, 10) };
  }, [allData]);

  useEffect(() => {
    if (!showEvents || !dateRange) return;
    apiGet<{ events: MarketEvent[] }>(
      `/events/range?start_date=${dateRange.start}&end_date=${dateRange.end}&min_importance=2`
    )
      .then((d) => setDbEvents(d.events || []))
      .catch(() => setDbEvents([]));
  }, [dateRange, showEvents]);

  // Merge DB + local events, deduplicate, sort by date
  const allEvents = useMemo<MarketEvent[]>(() => {
    if (!showEvents || !dateRange) return [];
    const localEvents = filterLocalEvents(dateRange.start, dateRange.end);
    const merged = new Map<string, MarketEvent>();
    for (const e of localEvents) merged.set(`${e.date}|${e.label}`, e);
    for (const e of dbEvents) merged.set(`${e.date}|${e.label}`, e);
    return [...merged.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [dateRange, showEvents, dbEvents]);

  // Events visible in current zoom range
  const visibleEvents = useMemo<MarketEvent[]>(() => {
    if (!showEvents || chartData.length < 2) return [];
    const start = chartData[0].time.slice(0, 10);
    const end = chartData[chartData.length - 1].time.slice(0, 10);
    return allEvents.filter((e) => e.date >= start && e.date <= end);
  }, [allEvents, chartData, showEvents]);

  // For chart lines: pick top events by importance, limit count to avoid clutter
  const chartLineEvents = useMemo(() => {
    if (visibleEvents.length <= MAX_CHART_LINES) return visibleEvents;
    // Sort by importance desc, take top N
    return [...visibleEvents]
      .sort((a, b) => (b.importance ?? 3) - (a.importance ?? 3))
      .slice(0, MAX_CHART_LINES)
      .sort((a, b) => a.date.localeCompare(b.date));
  }, [visibleEvents]);

  // Match event dates to closest chart data point
  const matchEventToChart = (evt: MarketEvent): string | null => {
    let matchTime: string | null = null;
    let minDist = Infinity;
    const evtMs = new Date(evt.date).getTime();
    for (const d of chartData) {
      const dist = Math.abs(new Date(d.time).getTime() - evtMs);
      if (dist < minDist) { minDist = dist; matchTime = d.time; }
    }
    return matchTime && minDist <= 5 * 86400000 ? matchTime : null;
  };

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
      <div style={{ borderRadius: "8px", flex: fullscreen ? 1 : undefined, minHeight: fullscreen ? 0 : undefined }}>
        <ResponsiveContainer width="100%" height={fullscreen ? "100%" : 360}>
          <LineChart data={chartData} margin={{ top: 30, right: 16, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
            <XAxis
              dataKey="time"
              fontSize={11}
              interval={tickInterval(chartData.length)}
              minTickGap={chartData.length <= 40 ? 16 : 28}
              tickFormatter={(v: string) => formatChartDate(v, periodLabel)}
            />
            <YAxis
              fontSize={11}
              domain={yDomain}
              tickCount={6}
              tickFormatter={(v: number) => Math.round(v).toLocaleString()}
              width={80}
            />
            <Tooltip
              formatter={(v: number) => wonFormatter(v)}
              labelFormatter={(v: string) => tooltipDateFormatter(v)}
            />
            <Legend />
            <Line
              type="linear"
              isAnimationActive={false}
              dataKey="close"
              stroke="var(--color-accent)"
              strokeWidth={2}
              dot={renderDot as any}
              connectNulls
              name={t("analysis.currentPrice")}
            />
            {/* Event lines — no labels on chart, just colored dashed lines */}
            {showEvents && chartLineEvents.map((evt) => {
              const matchTime = matchEventToChart(evt);
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
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Zoom slider */}
      <div className="flex gap-sm items-center" style={{ padding: "8px 0", fontSize: "11px" }}>
        <span className="text-secondary">Zoom:</span>
        <input
          type="range" min={0} max={Math.max(0, rangeEnd - 5)} value={rangeStart}
          onChange={(e) => setRangeStart(Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--color-accent)" }}
        />
        <input
          type="range" min={Math.min(100, rangeStart + 5)} max={100} value={rangeEnd}
          onChange={(e) => setRangeEnd(Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--color-accent)" }}
        />
        <span className="text-secondary">{chartData.length}pts</span>
      </div>

      {(sma20 || sma60) && (
        <div className="flex gap-xl text-secondary" style={{ marginTop: "4px", fontSize: "12px" }}>
          {sma20 && <span>SMA20: {sma20.toLocaleString()}</span>}
          {sma60 && <span>SMA60: {sma60.toLocaleString()}</span>}
        </div>
      )}

      {/* Event panel — collapsible, clean layout */}
      {showEvents && visibleEvents.length > 0 && (
        <div style={{ marginTop: 8, borderTop: "1px solid var(--color-border-light)", paddingTop: 8 }}>
          <div
            className="flex items-center gap-sm"
            style={{ cursor: "pointer", fontSize: 12, userSelect: "none" }}
            onClick={() => setEventsExpanded((v) => !v)}
          >
            <span style={{ fontSize: 14 }}>{eventsExpanded ? "▼" : "▶"}</span>
            <span className="font-bold">{t("analysis.events")} ({visibleEvents.length})</span>
            <div className="flex gap-sm" style={{ marginLeft: 8 }}>
              {["policy", "geopolitics", "economy", "market", "disaster"].map((cat) => {
                const count = visibleEvents.filter((e) => e.category === cat).length;
                if (!count) return null;
                return (
                  <span key={cat} style={{ color: getEventColor(cat), fontSize: 11 }}>
                    ■{count}
                  </span>
                );
              })}
            </div>
          </div>
          {eventsExpanded && (
            <div style={{ marginTop: 6, maxHeight: 200, overflowY: "auto" }}>
              <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                <tbody>
                  {visibleEvents.map((e) => (
                    <tr key={`${e.date}-${e.label}`} style={{ borderBottom: "1px solid #f5f5f5" }}>
                      <td style={{ padding: "3px 6px", whiteSpace: "nowrap", color: "var(--color-text-secondary)" }}>
                        {e.date}
                      </td>
                      <td style={{ padding: "3px 6px" }}>
                        <span style={{ color: getEventColor(e.category), fontWeight: 600 }}>■</span>
                      </td>
                      <td style={{ padding: "3px 6px" }}>
                        {e.url ? (
                          <a href={e.url} target="_blank" rel="noopener noreferrer"
                            style={{ color: getEventColor(e.category), textDecoration: "none" }}
                            onMouseOver={(ev) => { (ev.target as HTMLElement).style.textDecoration = "underline"; }}
                            onMouseOut={(ev) => { (ev.target as HTMLElement).style.textDecoration = "none"; }}
                          >
                            {e.label}
                          </a>
                        ) : (
                          <span style={{ color: getEventColor(e.category) }}>{e.label}</span>
                        )}
                      </td>
                      <td style={{ padding: "3px 6px", color: "var(--color-text-secondary)" }}>
                        {e.description}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
