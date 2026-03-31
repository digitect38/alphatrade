import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import { apiGet } from "../hooks/useApi";

interface BenchmarkData {
  stock_code: string;
  stock_name: string;
  sector?: string;
  period: number;
  series: Record<string, { date: string; value: number }[]>;
  summary: Record<string, number>;
}

export default function BenchmarkChart({
  stockCode, period, t: _t,
}: {
  stockCode: string;
  period?: number;
  t?: (k: string) => string;
}) {
  const [data, setData] = useState<BenchmarkData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!/^\d{6}$/.test(stockCode)) return;
    setLoading(true);
    apiGet<BenchmarkData>(`/strategy/benchmark?stock_code=${stockCode}&period=${period || 60}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [stockCode, period]);

  if (loading) return <div className="card text-secondary p-xl">벤치마크 로딩 중...</div>;
  if (!data) return null;

  // Merge all series by date
  const dateMap = new Map<string, Record<string, number>>();
  for (const [key, series] of Object.entries(data.series)) {
    for (const pt of series) {
      if (!dateMap.has(pt.date)) dateMap.set(pt.date, {});
      dateMap.get(pt.date)![key] = pt.value;
    }
  }
  const chartData = [...dateMap.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([date, vals]) => ({ date, ...vals }));

  const s = data.summary;

  return (
    <div className="card">
      <h3 className="card-title">벤치마크 비교</h3>

      {/* Summary cards */}
      <div className="flex gap-lg flex-wrap" style={{ marginBottom: "12px", fontSize: "13px" }}>
        <div>
          <span className="font-bold">{data.stock_name}</span>
          <span className={s[`${stockCode}_return`] >= 0 ? "text-profit" : "text-loss"} style={{ marginLeft: "6px" }}>
            {s[`${stockCode}_return`] >= 0 ? "+" : ""}{s[`${stockCode}_return`]}%
          </span>
        </div>
        <div>
          <span className="text-secondary">KOSPI</span>
          <span className={s.kospi_return >= 0 ? "text-profit" : "text-loss"} style={{ marginLeft: "6px" }}>
            {s.kospi_return >= 0 ? "+" : ""}{s.kospi_return}%
          </span>
        </div>
        <div>
          <span className="text-secondary">KOSDAQ</span>
          <span className={s.kosdaq_return >= 0 ? "text-profit" : "text-loss"} style={{ marginLeft: "6px" }}>
            {s.kosdaq_return >= 0 ? "+" : ""}{s.kosdaq_return}%
          </span>
        </div>
        {s.sector_return != null && (
          <div>
            <span className="text-secondary">섹터평균</span>
            <span className={s.sector_return >= 0 ? "text-profit" : "text-loss"} style={{ marginLeft: "6px" }}>
              {s.sector_return >= 0 ? "+" : ""}{s.sector_return}%
            </span>
          </div>
        )}
        {s.portfolio_return != null && (
          <div>
            <span className="text-secondary">내 투자</span>
            <span className={s.portfolio_return >= 0 ? "text-profit" : "text-loss"} style={{ marginLeft: "6px" }}>
              {s.portfolio_return >= 0 ? "+" : ""}{s.portfolio_return}%
            </span>
          </div>
        )}
        <div style={{ borderLeft: "1px solid #ddd", paddingLeft: "12px" }}>
          <span className="text-secondary">알파(KOSPI)</span>
          <span className={`font-heavy ${s.alpha_vs_kospi >= 0 ? "text-profit" : "text-loss"}`} style={{ marginLeft: "6px" }}>
            {s.alpha_vs_kospi >= 0 ? "+" : ""}{s.alpha_vs_kospi}%p
          </span>
        </div>
      </div>

      {/* Chart */}
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top: 10, right: 12, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="date"
              fontSize={11}
              tickFormatter={(v: string) => {
                const d = new Date(v);
                return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
              }}
            />
            <YAxis
              fontSize={11}
              tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`}
            />
            <Tooltip
              formatter={(v: number, name: string) => [`${v > 0 ? "+" : ""}${v.toFixed(2)}%`, name]}
              labelFormatter={(v: string) => new Date(v).toLocaleDateString("ko-KR")}
            />
            <Legend />
            <ReferenceLine y={0} stroke="#ccc" strokeDasharray="3 3" />
            <Line
              type="linear" dataKey={stockCode} stroke="var(--color-accent)"
              strokeWidth={2.5} dot={false} name={data.stock_name}
            />
            <Line
              type="linear" dataKey="KOSPI" stroke="#dc2626"
              strokeWidth={1.5} dot={false} strokeDasharray="5 3" name="KOSPI"
            />
            <Line
              type="linear" dataKey="KOSDAQ" stroke="#2563eb"
              strokeWidth={1.5} dot={false} strokeDasharray="5 3" name="KOSDAQ"
            />
            {data.series.sector && (
              <Line
                type="linear" dataKey="sector" stroke="#16a34a"
                strokeWidth={1.5} dot={false} strokeDasharray="3 3" name={`섹터평균 (${data.sector || ""})`}
              />
            )}
            {data.series.portfolio && (
              <Line
                type="linear" dataKey="portfolio" stroke="#d97706"
                strokeWidth={2} dot={false} name="내 투자"
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
