import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import type { OHLCVRecord } from "../types";

export default function TechnicalChart({
  data,
  sma20,
  sma60,
  t,
}: {
  data: OHLCVRecord[];
  sma20?: number | null;
  sma60?: number | null;
  t: (k: string) => string;
}) {
  const chartData = data.map((d) => ({
    date: new Date(d.time).toLocaleDateString("ko-KR", { month: "short", day: "numeric" }),
    close: d.close,
  }));

  return (
    <div className="card">
      <h3 className="card-title">{t("analysis.priceChart")}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
          <XAxis dataKey="date" fontSize={11} />
          <YAxis fontSize={11} domain={["auto", "auto"]} />
          <Tooltip />
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
