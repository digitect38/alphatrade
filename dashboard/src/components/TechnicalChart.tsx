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
} from "recharts";
import type { OHLCVRecord } from "../types";

type ChartPoint = {
  time: string;
  label: string;
  close: number;
};

export default function TechnicalChart({
  data,
  sma20,
  sma60,
  periodLabel,
  t,
}: {
  data: OHLCVRecord[];
  sma20?: number | null;
  sma60?: number | null;
  periodLabel?: string;
  t: (k: string) => string;
}) {
  const sourceData = useMemo<ChartPoint[]>(
    () =>
      data.map((d) => ({
        time: d.time,
        label: formatDateLabel(d.time, periodLabel),
        close: toNumber(d.close),
      })),
    [data, periodLabel],
  );

  const chartData = useMemo<ChartPoint[]>(
    () => downsampleChartData(sourceData, maxChartPoints(periodLabel)),
    [sourceData, periodLabel],
  );

  const extrema = useMemo(() => {
    if (!sourceData.length) return null;

    const latest = sourceData[sourceData.length - 1];
    let minPoint = sourceData[0];
    let maxPoint = sourceData[0];

    for (const point of sourceData) {
      if (point.close < minPoint.close) minPoint = point;
      if (point.close > maxPoint.close) maxPoint = point;
    }

    return {
      latest,
      minPoint,
      maxPoint,
      minVsCurrentPct: computeChangePct(minPoint.close, latest.close),
      maxVsCurrentPct: computeChangePct(maxPoint.close, latest.close),
    };
  }, [sourceData]);

  const yDomain = useMemo(() => {
    if (!chartData.length) return ["auto", "auto"] as [string, string];

    const closes = chartData.map((item) => item.close).filter((value) => Number.isFinite(value));

    if (!closes.length) return ["auto", "auto"] as [string, string];

    const minPrice = Math.min(...closes);
    const maxPrice = Math.max(...closes);
    const rawSpan = maxPrice - minPrice;
    const fallbackSpan = Math.max(maxPrice * 0.02, 1);
    const span = Math.max(rawSpan, fallbackSpan);
    const paddingRatio = 0.08;
    const padding = span * paddingRatio;
    const lower = Math.max(0, minPrice - padding);
    const upper = maxPrice + padding;

    return [roundDownAxis(lower), roundUpAxis(upper)] as [number, number];
  }, [chartData]);

  const xTickInterval = useMemo(() => tickIntervalForLength(chartData.length), [chartData.length]);

  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{t("analysis.priceChart")}</h3>
        {periodLabel && <span className="text-secondary">{t("analysis.period")}: {periodLabel}</span>}
      </div>
      {extrema ? (
        <div className="analysis-chart-meta">
          <span className="analysis-chart-meta-item">
            <strong>{t("analysis.highPoint")}</strong> {extrema.maxPoint.close.toLocaleString()}{t("common.won")}
            <span className="text-secondary"> ({formatSignedPct(extrema.maxVsCurrentPct)})</span>
          </span>
          <span className="analysis-chart-meta-item">
            <strong>{t("analysis.lowPoint")}</strong> {extrema.minPoint.close.toLocaleString()}{t("common.won")}
            <span className="text-secondary"> ({formatSignedPct(extrema.minVsCurrentPct)})</span>
          </span>
        </div>
      ) : null}
      <div style={{ overflow: "hidden", borderRadius: "8px" }}>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ top: 20, right: 12, bottom: 20, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
          <XAxis
            dataKey="time"
            fontSize={11}
            interval={xTickInterval}
            minTickGap={chartData.length <= 40 ? 16 : 28}
            tickFormatter={(value: string) => formatDateLabel(value, periodLabel)}
          />
          <YAxis
            fontSize={11}
            domain={yDomain}
            tickFormatter={(value: number) => `${Math.round(value).toLocaleString()}`}
            width={80}
          />
          <Tooltip formatter={(value: number) => `${Number(value).toLocaleString()}원`} />
          <Legend />
          <Line
            type="linear"
            isAnimationActive={false}
            dataKey="close"
            stroke="var(--color-accent)"
              strokeWidth={2}
              dot={false}
              connectNulls
              name={t("analysis.currentPrice")}
            />
          {/* ExtremaOverlay temporarily disabled for chart overflow debugging */}
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

function formatDateLabel(value: string, periodLabel?: string) {
  const date = new Date(value);

  if (periodLabel === "1Y") {
    return date.toLocaleDateString("ko-KR", { year: "2-digit", month: "short" });
  }

  if (periodLabel === "6M") {
    return date.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
  }

  if (periodLabel === "3Y" || periodLabel === "5Y" || periodLabel === "10Y" || periodLabel === "ALL") {
    return date.toLocaleDateString("ko-KR", { year: "2-digit", month: "short" });
  }

  return date.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

function roundDownAxis(value: number) {
  const unit = axisUnit(value);
  return Math.floor(value / unit) * unit;
}

function roundUpAxis(value: number) {
  const unit = axisUnit(value);
  return Math.ceil(value / unit) * unit;
}

function axisUnit(value: number) {
  if (value >= 100000) return 5000;
  if (value >= 10000) return 1000;
  if (value >= 1000) return 100;
  if (value >= 100) return 10;
  return 1;
}

function computeChangePct(base: number, current: number) {
  if (!base) return 0;
  return ((current / base) - 1) * 100;
}

function formatSignedPct(value: number) {
  const rounded = value.toFixed(2);
  return `${value >= 0 ? "+" : ""}${rounded}%`;
}


function maxChartPoints(periodLabel?: string) {
  if (periodLabel === "1M") return 120;
  if (periodLabel === "3M") return 140;
  if (periodLabel === "6M") return 150;
  if (periodLabel === "1Y") return 160;
  if (periodLabel === "3Y") return 180;
  if (periodLabel === "5Y") return 200;
  if (periodLabel === "10Y" || periodLabel === "ALL") return 220;
  return 120;
}

function downsampleChartData<T extends { close: number; time: string }>(data: T[], maxPoints: number): T[] {
  if (data.length <= maxPoints) return data;
  const step = data.length / maxPoints;
  const result: T[] = [];
  for (let i = 0; i < maxPoints; i++) {
    const idx = Math.min(Math.round(i * step), data.length - 1);
    result.push(data[idx]);
  }
  if (result[result.length - 1] !== data[data.length - 1]) {
    result.push(data[data.length - 1]);
  }
  return result;
}

function tickIntervalForLength(length: number) {
  if (length <= 30) return "preserveEnd" as const;
  if (length <= 80) return 8;
  if (length <= 140) return 16;
  if (length <= 200) return 24;
  return 32;
}

