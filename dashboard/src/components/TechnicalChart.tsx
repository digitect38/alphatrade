import { useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import type { OHLCVRecord } from "../types";

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
  const chartData = useMemo(
    () =>
      data.map((d) => ({
        date: formatDateLabel(d.time, periodLabel),
        close: d.close,
      })),
    [data, periodLabel],
  );

  const yDomain = useMemo(() => {
    if (!data.length) return ["auto", "auto"] as [string, string];

    // This chart renders close prices only, so autorange should follow the visible line.
    const closes = data.map((item) => item.close).filter((value) => Number.isFinite(value));

    if (!closes.length) return ["auto", "auto"] as [string, string];

    const minPrice = Math.min(...closes);
    const maxPrice = Math.max(...closes);
    const rawSpan = maxPrice - minPrice;
    const fallbackSpan = Math.max(maxPrice * 0.015, 1);
    const span = Math.max(rawSpan, fallbackSpan);
    const paddingRatio = periodLabel === "1M" ? 0.06 : periodLabel === "3M" ? 0.08 : 0.1;
    const padding = span * paddingRatio;
    const lower = Math.max(0, minPrice - padding);
    const upper = maxPrice + padding;

    return [roundDownAxis(lower), roundUpAxis(upper)] as [number, number];
  }, [data, periodLabel]);

  const xTickInterval = periodLabel === "1M" ? "preserveEnd" : periodLabel === "3M" ? 9 : periodLabel === "6M" ? 20 : 32;

  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{t("analysis.priceChart")}</h3>
        {periodLabel && <span className="text-secondary">{t("analysis.period")}: {periodLabel}</span>}
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
          <XAxis dataKey="date" fontSize={11} interval={xTickInterval} minTickGap={periodLabel === "1M" ? 16 : 28} />
          <YAxis
            fontSize={11}
            domain={yDomain}
            tickFormatter={(value: number) => `${Math.round(value).toLocaleString()}`}
            width={80}
          />
          <Tooltip formatter={(value: number) => `${Number(value).toLocaleString()}원`} />
          <Legend />
          <Line type="monotone" dataKey="close" stroke="var(--color-accent)" strokeWidth={2} dot={false} name={t("analysis.currentPrice")} />
        </LineChart>
      </ResponsiveContainer>
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
