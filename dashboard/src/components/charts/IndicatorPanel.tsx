/**
 * Reusable RSI and MACD indicator panels.
 */
import {
  Bar, CartesianGrid, ComposedChart, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

interface IndicatorPoint {
  label: string;
  rsi14?: number | null;
  macd?: number | null;
  macdSignal?: number | null;
  macdHist?: number | null;
}

export function RSIPanel({
  data, height = 120, syncId, t,
}: {
  data: IndicatorPoint[];
  height?: number;
  syncId?: string;
  t: (k: string) => string;
}) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-secondary)" }}>
        {t("asset.indicator.rsi")}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} syncId={syncId}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
          <XAxis dataKey="label" hide />
          <YAxis domain={[0, 100]} hide />
          <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 4" />
          <ReferenceLine y={30} stroke="#10b981" strokeDasharray="4 4" />
          <Tooltip formatter={(v: number) => [Number(v).toFixed(2), t("asset.indicator.rsi")]} />
          <Line type="monotone" dataKey="rsi14" stroke="#2563eb" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MACDPanel({
  data, height = 140, syncId, t,
}: {
  data: IndicatorPoint[];
  height?: number;
  syncId?: string;
  t: (k: string) => string;
}) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-secondary)" }}>
        {t("asset.indicator.macd")}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} syncId={syncId}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
          <XAxis dataKey="label" hide />
          <YAxis hide />
          <Tooltip formatter={(v: number) => [Number(v).toFixed(2), "MACD"]} />
          <Bar dataKey="macdHist" fill="rgba(14, 165, 233, 0.24)" />
          <Line type="monotone" dataKey="macd" stroke="#7c3aed" strokeWidth={2} dot={false} connectNulls />
          <Line type="monotone" dataKey="macdSignal" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
