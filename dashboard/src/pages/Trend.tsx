import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { apiGet } from "../hooks/useApi";

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
    <div className="page-content">
      {/* Sector Filter */}
      <div className="card">
        <div className="flex gap-sm items-center mb-md">
          <h3 className="card-title" style={{ marginBottom: 0 }}>{_t("trend.sectorFilter")}</h3>
          <button onClick={selectAll} className="filter-btn">{_t("trend.all")}</button>
          <button onClick={selectNone} className="filter-btn">{_t("trend.reset")}</button>
        </div>
        <div className="flex flex-wrap gap-sm">
          {sectors.map((sec, i) => {
            const active = selectedSectors.has(sec.sector);
            const color = COLORS[i % COLORS.length];
            return (
              <button
                key={sec.sector}
                onClick={() => toggleSector(sec.sector)}
                className="filter-chip"
                style={{
                  borderColor: color,
                  background: active ? color : "transparent",
                  color: active ? "#fff" : color,
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
        <div className="card">
          <h3 className="card-title">{_t("trend.cumulativeReturn")}</h3>
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
      <div className="card">
        <h3 className="card-title">{_t("trend.sectorRanking")}</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: "40px" }}>#</th>
              <th>{_t("th.sector")}</th>
              <th className="text-right">{_t("trend.stockCount")}</th>
              <th className="text-right">{_t("trend.avgChange")}</th>
              <th className="text-right">{_t("trend.cumReturn")}</th>
              <th className="text-center">{_t("trend.detail")}</th>
            </tr>
          </thead>
          <tbody>
            {overview.map((sec, i) => {
              const trendSec = sectors.find((s) => s.sector === sec.sector);
              const cumReturn = trendSec?.cumulative_return ?? 0;
              const changeClass = sec.avg_change > 0 ? "text-up" : sec.avg_change < 0 ? "text-down" : "text-neutral";
              const cumClass = cumReturn > 0 ? "text-up" : cumReturn < 0 ? "text-down" : "text-neutral";
              const expanded = expandedSector === sec.sector;

              return (
                <>
                  <tr key={sec.sector}>
                    <td className="font-bold text-secondary">{i + 1}</td>
                    <td className="font-bold">{sec.sector}</td>
                    <td className="text-right">{sec.stock_count}</td>
                    <td className={"text-right font-heavy " + changeClass}>
                      {sec.avg_change > 0 ? "+" : ""}{sec.avg_change}%
                    </td>
                    <td className={"text-right font-heavy " + cumClass}>
                      {cumReturn > 0 ? "+" : ""}{cumReturn}%
                    </td>
                    <td className="text-center">
                      <button
                        onClick={() => setExpandedSector(expanded ? null : sec.sector)}
                        className="btn btn-sm"
                        style={{ background: "none", border: "1px solid #ddd" }}
                      >
                        {expanded ? _t("trend.collapse") : _t("trend.stocks")}
                      </button>
                    </td>
                  </tr>
                  {expanded && sec.stocks.map((stock) => {
                    const sClass = stock.change_pct > 0 ? "text-up" : stock.change_pct < 0 ? "text-down" : "text-neutral";
                    return (
                      <tr key={stock.stock_code} className="expanded-row">
                        <td />
                        <td style={{ fontSize: "12px" }}>
                          <span className="text-secondary">{stock.stock_code}</span> {stock.stock_name}
                        </td>
                        <td />
                        <td className={"text-right font-bold " + sClass} style={{ fontSize: "12px" }}>
                          {stock.change_pct > 0 ? "+" : ""}{stock.change_pct}%
                        </td>
                        <td className="text-right" style={{ fontSize: "12px" }}>
                          {stock.price.toLocaleString()}{_t("common.won")}
                        </td>
                        <td className="text-right text-secondary" style={{ fontSize: "11px" }}>
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
