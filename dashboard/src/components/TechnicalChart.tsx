import { useMemo } from "react";
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
  Brush,
} from "recharts";
import type { OHLCVRecord } from "../types";

type ChartPoint = { time: string; close: number; };

export default function TechnicalChart({
  data, sma20, sma60, periodLabel, t,
}: {
  data: OHLCVRecord[];
  sma20?: number | null;
  sma60?: number | null;
  periodLabel?: string;
  t: (k: string) => string;
}) {
  const chartData = useMemo<ChartPoint[]>(() => {
    const src = data.map((d) => ({ time: d.time, close: toNumber(d.close) }));
    return downsample(src, maxPoints(periodLabel));
  }, [data, periodLabel]);

  const extrema = useMemo(() => {
    if (chartData.length < 2) return null;
    const latest = chartData[chartData.length - 1];
    let minIdx = 0, maxIdx = 0;
    for (let i = 1; i < chartData.length; i++) {
      if (chartData[i].close < chartData[minIdx].close) minIdx = i;
      if (chartData[i].close > chartData[maxIdx].close) maxIdx = i;
    }
    if (chartData[minIdx].close === chartData[maxIdx].close) return null;
    return { minIdx, maxIdx, latest };
  }, [chartData]);

  const yDomain = useMemo(() => {
    const closes = chartData.map((d) => d.close).filter(Number.isFinite);
    if (!closes.length) return ["auto", "auto"] as [string, string];
    const min = Math.min(...closes), max = Math.max(...closes);
    const span = Math.max(max - min, max * 0.02, 1);
    return [roundAxis(min - span * 0.12, "down"), roundAxis(max + span * 0.18, "up")] as [number, number];
  }, [chartData]);

  // Custom dot renderer — show only high/low points
  const renderDot = (props: any) => {
    if (!extrema) return null;
    const { cx, cy, index } = props;
    if (index !== extrema.maxIdx && index !== extrema.minIdx) return null;

    const isHigh = index === extrema.maxIdx;
    const pt = chartData[index];
    const pct = ((pt.close / extrema.latest.close) - 1) * 100;
    const color = isHigh ? "#dc2626" : "#2563eb";
    const label = `${pt.close.toLocaleString()}원 (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`;
    const yOff = isHigh ? -16 : 20;

    return (
      <g key={`extrema-${index}`}>
        <circle cx={cx} cy={cy} r={5} fill={color} stroke="#fff" strokeWidth={2} />
        <text x={cx} y={cy + yOff} textAnchor="middle" fill={color} fontSize={11} fontWeight={700}>
          {label}
        </text>
      </g>
    );
  };

  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{t("analysis.priceChart")}</h3>
        {periodLabel && <span className="text-secondary">{t("analysis.period")}: {periodLabel}</span>}
      </div>
      <div style={{ overflow: "hidden", borderRadius: "8px" }}>
        <ResponsiveContainer width="100%" height={380}>
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
            {/* Brush for zoom/pan */}
            <Brush
              dataKey="time"
              height={28}
              stroke="var(--color-accent)"
              fill="#f8fafc"
              tickFormatter={(v: string) => fmtDate(v, periodLabel)}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {(sma20 || sma60) && (
        <div className="flex gap-xl text-secondary" style={{ marginTop: "8px", fontSize: "12px" }}>
          {sma20 && <span>SMA20: {sma20.toLocaleString()}</span>}
          {sma60 && <span>SMA60: {sma60.toLocaleString()}</span>}
        </div>
      )}
    </div>
  );
}

/* === Helpers === */

function fmtDate(value: string, period?: string) {
  const d = new Date(value);
  if (period === "1Y" || period === "3Y" || period === "5Y" || period === "10Y" || period === "ALL")
    return d.toLocaleDateString("ko-KR", { year: "2-digit", month: "short" });
  if (period === "6M")
    return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
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
