import { useMemo, useState } from "react";
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
} from "recharts";
import type { OHLCVRecord } from "../types";

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
    return downsample(src, maxPoints(periodLabel));
  }, [data, periodLabel]);

  // Range slider state
  const [rangeStart, setRangeStart] = useState(0);
  const [rangeEnd, setRangeEnd] = useState(100); // percentage

  // Reset on period change
  useMemo(() => { setRangeStart(0); setRangeEnd(100); }, [periodLabel]);

  // Slice data by range
  const chartData = useMemo(() => {
    if (rangeStart === 0 && rangeEnd === 100) return allData;
    const startIdx = Math.floor((rangeStart / 100) * allData.length);
    const endIdx = Math.max(startIdx + 2, Math.ceil((rangeEnd / 100) * allData.length));
    return allData.slice(startIdx, endIdx);
  }, [allData, rangeStart, rangeEnd]);

  // Extrema from visible data
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

  // Y domain from visible data — auto zoom
  const yDomain = useMemo((): [number, number] => {
    const closes = chartData.map((d) => d.close).filter(Number.isFinite);
    if (!closes.length) return [0, 100];
    const min = Math.min(...closes), max = Math.max(...closes);
    const span = Math.max(max - min, max * 0.02, 1);
    return [roundAxis(min - span * 0.12, "down"), roundAxis(max + span * 0.18, "up")];
  }, [chartData]);

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

  const isZoomed = rangeStart > 0 || rangeEnd < 100;

  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{t("analysis.priceChart")}</h3>
        <div className="flex gap-sm items-center">
          {periodLabel && <span className="text-secondary">{t("analysis.period")}: {periodLabel}</span>}
          {isZoomed && (
            <button className="btn btn-sm" style={{ fontSize: "11px" }} onClick={() => { setRangeStart(0); setRangeEnd(100); }}>
              Reset Zoom
            </button>
          )}
        </div>
      </div>
      <div style={{ overflow: "hidden", borderRadius: "8px" }}>
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={chartData} margin={{ top: 30, right: 16, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
            <XAxis
              dataKey="time"
              fontSize={11}
              interval={tickInterval(chartData.length)}
              minTickGap={chartData.length <= 40 ? 16 : 28}
              tickFormatter={(v: string) => fmtDate(v, periodLabel)}
            />
            <YAxis
              fontSize={11}
              domain={yDomain}
              tickCount={6}
              tickFormatter={(v: number) => Math.round(v).toLocaleString()}
              width={80}
            />
            <Tooltip
              formatter={(v: number) => `${Number(v).toLocaleString()}원`}
              labelFormatter={(v: string) => new Date(v).toLocaleDateString("ko-KR")}
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
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* Range slider for zoom */}
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
    </div>
  );
}

function fmtDate(value: string, period?: string) {
  const d = new Date(value);
  if (["1Y","3Y","5Y","10Y","ALL"].includes(period || ""))
    return d.toLocaleDateString("ko-KR", { year: "2-digit", month: "short" });
  return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

function roundAxis(value: number, dir: "up" | "down") {
  const u = value >= 100000 ? 5000 : value >= 10000 ? 1000 : value >= 1000 ? 100 : 10;
  return dir === "up" ? Math.ceil(value / u) * u : Math.max(0, Math.floor(value / u) * u);
}

function maxPoints(p?: string) {
  const m: Record<string, number> = { "1M":120,"3M":140,"6M":150,"1Y":160,"3Y":180,"5Y":200,"10Y":220,"ALL":220 };
  return m[p || ""] || 120;
}

function downsample<T extends { close: number; time: string }>(data: T[], max: number): T[] {
  if (data.length <= max) return data;
  const step = data.length / max;
  const r: T[] = [];
  for (let i = 0; i < max; i++) r.push(data[Math.min(Math.round(i * step), data.length - 1)]);
  if (r[r.length - 1] !== data[data.length - 1]) r.push(data[data.length - 1]);
  return r;
}

function tickInterval(len: number) {
  if (len <= 30) return "preserveEnd" as const;
  if (len <= 80) return 8;
  if (len <= 140) return 16;
  return 24;
}
