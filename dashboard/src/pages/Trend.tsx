import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { apiGet } from "../hooks/useApi";

const card = { background: "#fff", borderRadius: "8px", padding: "20px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" } as const;

interface TrendPoint {
  date: string;
  return_pct: number;
  cumulative: number;
}

interface StockInfo {
  stock_code: string;
  stock_name: string;
  price: number;
}

interface SectorTrend {
  sector: string;
  stock_count: number;
  trend: TrendPoint[];
  cumulative_return: number;
  stocks: StockInfo[];
}

interface SectorOverviewStock {
  stock_code: string;
  stock_name: string;
  price: number;
  change_pct: number;
  volume: number;
}

interface SectorOverview {
  sector: string;
  avg_change: number;
  stock_count: number;
  stocks: SectorOverviewStock[];
}

const COLORS = [
  "#e11d48", "#2563eb", "#16a34a", "#d97706", "#7c3aed",
  "#0891b2", "#be185d", "#65a30d", "#c2410c", "#6d28d9",
  "#0d9488", "#a21caf",
];

export default function TrendPage({ t: _t }: { t: (k: string) => string }) {
  const [sectors, setSectors] = useState<SectorTrend[]>([]);
  const [overview, setOverview] = useState<SectorOverview[]>([]);
  const [selectedSectors, setSelectedSectors] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [expandedSector, setExpandedSector] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiGet<{ sectors: SectorTrend[] }>("/index/sectors?days=20"),
      apiGet<{ sectors: SectorOverview[] }>("/index/overview"),
    ])
      .then(([trend, ov]) => {
        setSectors(trend.sectors || []);
        setOverview(ov.sectors || []);
        setSelectedSectors(new Set((trend.sectors || []).map((s) => s.sector)));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const toggleSector = (sector: string) => {
    setSelectedSectors((prev) => {
      const next = new Set(prev);
      if (next.has(sector)) next.delete(sector);
      else next.add(sector);
      return next;
    });
  };

  const selectAll = () => setSelectedSectors(new Set(sectors.map((s) => s.sector)));
  const selectNone = () => setSelectedSectors(new Set());

  // Build combined chart data
  const chartData: Record<string, Record<string, number>>[] = [];
  if (sectors.length > 0) {
    const dateMap = new Map<string, Record<string, number>>();
    for (const sec of sectors) {
      if (!selectedSectors.has(sec.sector)) continue;
      for (const point of sec.trend) {
        if (!dateMap.has(point.date)) dateMap.set(point.date, { date: 0 });
        dateMap.get(point.date)![sec.sector] = point.cumulative;
      }
    }
    // Sort by date
    const sorted = [...dateMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    for (const [date, vals] of sorted) {
      chartData.push({ date: { toString: () => date } as any, ...vals, _date: date } as any);
    }
  }

  if (loading) return <p>{_t("common.loading")}</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Sector Filter */}
      <div style={card}>
        <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px" }}>
          <h3 style={{ margin: 0, fontSize: "14px" }}>{_t("trend.sectorFilter")}</h3>
          <button onClick={selectAll} style={filterBtn}>{_t("trend.all")}</button>
          <button onClick={selectNone} style={filterBtn}>{_t("trend.reset")}</button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {sectors.map((sec, i) => {
            const active = selectedSectors.has(sec.sector);
            const color = COLORS[i % COLORS.length];
            return (
              <button
                key={sec.sector}
                onClick={() => toggleSector(sec.sector)}
                style={{
                  padding: "6px 14px",
                  borderRadius: "20px",
                  border: `2px solid ${color}`,
                  background: active ? color : "transparent",
                  color: active ? "#fff" : color,
                  cursor: "pointer",
                  fontSize: "13px",
                  fontWeight: 600,
                  transition: "all 0.15s",
                }}
              >
                {sec.sector} ({sec.cumulative_return >= 0 ? "+" : ""}{sec.cumulative_return}%)
              </button>
            );
          })}
        </div>
      </div>

      {/* Cumulative Return Chart */}
      {chartData.length > 0 && (
        <div style={card}>
          <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("trend.cumulativeReturn")}</h3>
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="_date" fontSize={11} />
              <YAxis fontSize={11} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip
                formatter={(v: number, name: string) => [`${v.toFixed(2)}%`, name]}
                labelFormatter={(label: string) => `날짜: ${label}`}
              />
              <Legend />
              {sectors
                .filter((s) => selectedSectors.has(s.sector))
                .map((sec) => (
                  <Line
                    key={sec.sector}
                    type="monotone"
                    dataKey={sec.sector}
                    stroke={COLORS[sectors.indexOf(sec) % COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Sector Rankings */}
      <div style={card}>
        <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("trend.sectorRanking")}</h3>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #eee", textAlign: "left" }}>
              <th style={{ padding: "8px", width: "40px" }}>#</th>
              <th style={{ padding: "8px" }}>{_t("th.sector")}</th>
              <th style={{ padding: "8px", textAlign: "right" }}>{_t("trend.stockCount")}</th>
              <th style={{ padding: "8px", textAlign: "right" }}>{_t("trend.avgChange")}</th>
              <th style={{ padding: "8px", textAlign: "right" }}>{_t("trend.cumReturn")}</th>
              <th style={{ padding: "8px", textAlign: "center" }}>{_t("trend.detail")}</th>
            </tr>
          </thead>
          <tbody>
            {overview.map((sec, i) => {
              const trendSec = sectors.find((s) => s.sector === sec.sector);
              const cumReturn = trendSec?.cumulative_return ?? 0;
              const color = sec.avg_change > 0 ? "#dc2626" : sec.avg_change < 0 ? "#3b82f6" : "#888";
              const cumColor = cumReturn > 0 ? "#dc2626" : cumReturn < 0 ? "#3b82f6" : "#888";
              const expanded = expandedSector === sec.sector;

              return (
                <>
                  <tr key={sec.sector} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "8px", fontWeight: 600, color: "#888" }}>{i + 1}</td>
                    <td style={{ padding: "8px", fontWeight: 600 }}>{sec.sector}</td>
                    <td style={{ padding: "8px", textAlign: "right" }}>{sec.stock_count}</td>
                    <td style={{ padding: "8px", textAlign: "right", color, fontWeight: 700 }}>
                      {sec.avg_change > 0 ? "+" : ""}{sec.avg_change}%
                    </td>
                    <td style={{ padding: "8px", textAlign: "right", color: cumColor, fontWeight: 700 }}>
                      {cumReturn > 0 ? "+" : ""}{cumReturn}%
                    </td>
                    <td style={{ padding: "8px", textAlign: "center" }}>
                      <button
                        onClick={() => setExpandedSector(expanded ? null : sec.sector)}
                        style={{ background: "none", border: "1px solid #ddd", borderRadius: "4px", padding: "2px 8px", cursor: "pointer", fontSize: "12px" }}
                      >
                        {expanded ? _t("trend.collapse") : _t("trend.stocks")}
                      </button>
                    </td>
                  </tr>
                  {expanded && sec.stocks.map((stock) => {
                    const sColor = stock.change_pct > 0 ? "#dc2626" : stock.change_pct < 0 ? "#3b82f6" : "#888";
                    return (
                      <tr key={stock.stock_code} style={{ background: "#fafafa", borderBottom: "1px solid #f5f5f5" }}>
                        <td style={{ padding: "6px 8px" }} />
                        <td style={{ padding: "6px 8px", fontSize: "12px" }}>
                          <span style={{ color: "#888" }}>{stock.stock_code}</span> {stock.stock_name}
                        </td>
                        <td />
                        <td style={{ padding: "6px 8px", textAlign: "right", fontSize: "12px", color: sColor, fontWeight: 600 }}>
                          {stock.change_pct > 0 ? "+" : ""}{stock.change_pct}%
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontSize: "12px" }}>
                          {stock.price.toLocaleString()}{_t("common.won")}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontSize: "11px", color: "#888" }}>
                          {stock.volume.toLocaleString()}
                        </td>
                      </tr>
                    );
                  })}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const filterBtn = {
  padding: "4px 10px",
  border: "1px solid #ddd",
  borderRadius: "4px",
  background: "#f5f5f5",
  cursor: "pointer",
  fontSize: "12px",
} as const;
