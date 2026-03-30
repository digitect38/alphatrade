import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { apiGet } from "../hooks/useApi";

interface TrendPoint { date: string; return_pct: number; cumulative: number; }
interface StockInfo { stock_code: string; stock_name: string; price: number; }
interface SectorTrend {
  sector: string; stock_count: number; trend: TrendPoint[];
  cumulative_return: number; stocks: StockInfo[];
}
interface SectorOverviewStock {
  stock_code: string; stock_name: string; price: number;
  change_pct: number; volume: number;
}
interface SectorOverview {
  sector: string; avg_change: number; stock_count: number;
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
  const [tab, setTab] = useState<"chart" | "ranking">("chart");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiGet<{ sectors: SectorTrend[] }>("/index/sectors?days=20"),
      apiGet<{ sectors: SectorOverview[] }>("/index/overview"),
    ])
      .then(([trend, ov]) => {
        setSectors(trend.sectors || []);
        setOverview(ov.sectors || []);
        // Default: select top 10 sectors only (avoid chart overload)
        setSelectedSectors(new Set((trend.sectors || []).slice(0, 10).map((s) => s.sector)));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const toggleSector = (s: string) => {
    setSelectedSectors((prev) => {
      const next = new Set(prev);
      next.has(s) ? next.delete(s) : next.add(s);
      return next;
    });
  };

  // Build chart data from selected sectors only
  const chartData: Record<string, unknown>[] = [];
  if (sectors.length > 0) {
    const dateMap = new Map<string, Record<string, number>>();
    for (const sec of sectors) {
      if (!selectedSectors.has(sec.sector)) continue;
      for (const pt of sec.trend) {
        if (!dateMap.has(pt.date)) dateMap.set(pt.date, {});
        dateMap.get(pt.date)![sec.sector] = pt.cumulative;
      }
    }
    [...dateMap.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .forEach(([date, vals]) => chartData.push({ _date: date, ...vals }));
  }

  if (loading) return <p className="text-secondary p-xl">{_t("common.loading")}</p>;

  return (
    <div className="page-content">

      {/* ── Tab Switcher ── */}
      <div className="flex gap-sm">
        <button className={"btn btn-sm " + (tab === "chart" ? "btn-primary" : "")}
          style={tab !== "chart" ? { background: "#f0f0f0", color: "#333" } : undefined}
          onClick={() => setTab("chart")}>{_t("trend.cumulativeReturn")}</button>
        <button className={"btn btn-sm " + (tab === "ranking" ? "btn-primary" : "")}
          style={tab !== "ranking" ? { background: "#f0f0f0", color: "#333" } : undefined}
          onClick={() => setTab("ranking")}>{_t("trend.sectorRanking")}</button>
      </div>

      {/* ── TAB 1: 섹터 추세 차트 ── */}
      {tab === "chart" && (
        <>
          {/* Sector Filter — compact scrollable list */}
          <div className="card">
            <div className="flex gap-sm items-center mb-md">
              <h3 className="card-title" style={{ marginBottom: 0 }}>{_t("trend.sectorFilter")} ({selectedSectors.size}/{sectors.length})</h3>
              <button onClick={() => setSelectedSectors(new Set(sectors.slice(0, 10).map((s) => s.sector)))} className="filter-btn">Top 10</button>
              <button onClick={() => setSelectedSectors(new Set(sectors.map((s) => s.sector)))} className="filter-btn">{_t("trend.all")}</button>
              <button onClick={() => setSelectedSectors(new Set())} className="filter-btn">{_t("trend.reset")}</button>
            </div>
            <div style={{ maxHeight: "160px", overflowY: "auto", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "4px", fontSize: "12px" }}>
              {sectors.map((sec, i) => {
                const active = selectedSectors.has(sec.sector);
                const color = COLORS[i % COLORS.length];
                return (
                  <label key={sec.sector} className="flex items-center gap-xs" style={{ cursor: "pointer", padding: "3px 6px", borderRadius: "4px", background: active ? `${color}15` : "transparent" }}>
                    <input type="checkbox" checked={active} onChange={() => toggleSector(sec.sector)} style={{ accentColor: color }} />
                    <span style={{ color: active ? color : "#666", fontWeight: active ? 600 : 400 }}>
                      {sec.sector} <span className="text-secondary">({sec.cumulative_return >= 0 ? "+" : ""}{sec.cumulative_return}%)</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Chart */}
          {chartData.length > 0 && (
            <div className="card">
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="_date" fontSize={11} />
                  <YAxis fontSize={11} tickFormatter={(v: number) => `${v}%`} />
                  <Tooltip formatter={(v: number, name: string) => [`${v.toFixed(2)}%`, name]} />
                  <Legend />
                  {sectors.filter((s) => selectedSectors.has(s.sector)).map((sec) => (
                    <Line key={sec.sector} type="monotone" dataKey={sec.sector}
                      stroke={COLORS[sectors.indexOf(sec) % COLORS.length]} strokeWidth={2} dot={false} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {/* ── TAB 2: 섹터 순위 테이블 ── */}
      {tab === "ranking" && (
        <div className="card">
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
                const cumReturn = sectors.find((s) => s.sector === sec.sector)?.cumulative_return ?? 0;
                const chgCls = sec.avg_change > 0 ? "text-up" : sec.avg_change < 0 ? "text-down" : "text-neutral";
                const cumCls = cumReturn > 0 ? "text-up" : cumReturn < 0 ? "text-down" : "text-neutral";
                const expanded = expandedSector === sec.sector;

                return (
                  <tbody key={sec.sector}>
                    <tr>
                      <td className="font-bold text-secondary">{i + 1}</td>
                      <td className="font-bold">{sec.sector}</td>
                      <td className="text-right">{sec.stock_count}</td>
                      <td className={"text-right font-heavy " + chgCls}>
                        {sec.avg_change > 0 ? "+" : ""}{sec.avg_change}%
                      </td>
                      <td className={"text-right font-heavy " + cumCls}>
                        {cumReturn > 0 ? "+" : ""}{cumReturn}%
                      </td>
                      <td className="text-center">
                        <button onClick={() => setExpandedSector(expanded ? null : sec.sector)}
                          className="btn btn-sm" style={{ background: "none", border: "1px solid #ddd" }}>
                          {expanded ? _t("trend.collapse") : _t("trend.stocks")}
                        </button>
                      </td>
                    </tr>
                    {expanded && sec.stocks.map((stock) => {
                      const sCls = stock.change_pct > 0 ? "text-up" : stock.change_pct < 0 ? "text-down" : "text-neutral";
                      return (
                        <tr key={stock.stock_code} className="expanded-row">
                          <td />
                          <td style={{ fontSize: "12px" }}>
                            <span className="text-secondary">{stock.stock_code}</span> {stock.stock_name}
                          </td>
                          <td />
                          <td className={"text-right font-bold " + sCls} style={{ fontSize: "12px" }}>
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
                  </tbody>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
