import { useEffect, useState } from "react";
import { XAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts";
import { apiGet, apiPost } from "../hooks/useApi";
import type { BatchSignalResult, PortfolioStatus, StrategySignal } from "../types";

const card = (flex?: number) => ({
  background: "#fff", borderRadius: "12px", padding: "20px",
  boxShadow: "0 1px 4px rgba(0,0,0,0.08)", flex: flex || "unset",
}) as const;

const metricLabel = { fontSize: "12px", color: "#999", marginBottom: "2px", letterSpacing: "0.5px", textTransform: "uppercase" } as const;
const metricValue = { fontSize: "28px", fontWeight: 800, lineHeight: 1.2 } as const;

interface TradingStatus {
  time: string;
  total_value: number;
  cash: number;
  invested: number;
  daily_pnl: number;
  daily_return_pct: number;
  cumulative_return_pct: number;
  mdd_pct: number;
  positions_count: number;
}

export default function DashboardPage({ t }: { t: (k: string) => string }) {
  const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
  const [status, setStatus] = useState<TradingStatus | null>(null);
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [health, setHealth] = useState<{ status: string; db: string; redis: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiGet<PortfolioStatus>("/portfolio/status"),
      apiGet<TradingStatus>("/trading/status"),
      apiPost<BatchSignalResult>("/strategy/signals/batch", {}),
      apiGet<{ status: string; db: string; redis: string }>("/health"),
    ])
      .then(([p, s, sig, h]) => {
        setPortfolio(p);
        setStatus(s);
        setSignals(sig.signals || []);
        setHealth(h);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p style={{ padding: "40px", color: "#888" }}>{t("common.loading")}</p>;

  const initialCapital = 10_000_000;
  const totalValue = portfolio?.total_value || initialCapital;
  const totalReturn = ((totalValue / initialCapital) - 1) * 100;
  const dailyPnl = status?.daily_pnl || 0;
  const cash = portfolio?.cash || initialCapital;
  const cashRatio = totalValue > 0 ? (cash / totalValue) * 100 : 100;
  const mdd = status?.mdd_pct || 0;
  const posCount = portfolio?.positions_count || 0;

  const buySignals = signals.filter((s) => s.signal === "BUY");
  const sellSignals = signals.filter((s) => s.signal === "SELL");

  // Build equity mini-chart from positions
  const equityData = portfolio?.positions.map((p) => ({
    name: p.stock_name || p.stock_code,
    value: (p.current_price || p.avg_price) * p.quantity,
    pnl: p.unrealized_pnl_pct || 0,
  })) || [];

  // Signal distribution for bar chart
  const signalDist = signals.reduce(
    (acc, s) => {
      acc[s.signal] = (acc[s.signal] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );
  const signalChartData = [
    { name: "BUY", count: signalDist["BUY"] || 0, color: "#16a34a" },
    { name: "HOLD", count: signalDist["HOLD"] || 0, color: "#94a3b8" },
    { name: "SELL", count: signalDist["SELL"] || 0, color: "#dc2626" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>

      {/* Row 1: Key Metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "16px" }}>
        <div style={card()}>
          <div style={metricLabel}>{t("dash.totalValue")}</div>
          <div style={metricValue}>{fmt(totalValue)}</div>
          <div style={{ fontSize: "12px", color: "#999", marginTop: "2px" }}>{t("common.won")}</div>
        </div>
        <div style={card()}>
          <div style={metricLabel}>{t("dash.dailyPnl")}</div>
          <div style={{ ...metricValue, color: dailyPnl >= 0 ? "#16a34a" : "#dc2626" }}>
            {dailyPnl >= 0 ? "+" : ""}{fmt(dailyPnl)}
          </div>
          <div style={{ fontSize: "12px", color: "#999", marginTop: "2px" }}>{t("common.won")}</div>
        </div>
        <div style={card()}>
          <div style={metricLabel}>{t("dash.return")}</div>
          <div style={{ ...metricValue, color: totalReturn >= 0 ? "#16a34a" : "#dc2626" }}>
            {totalReturn >= 0 ? "+" : ""}{totalReturn.toFixed(2)}%
          </div>
        </div>
        <div style={card()}>
          <div style={metricLabel}>{t("dash.mdd")}</div>
          <div style={{ ...metricValue, color: mdd < -3 ? "#dc2626" : "#f59e0b" }}>
            {mdd.toFixed(2)}%
          </div>
        </div>
        <div style={card()}>
          <div style={metricLabel}>{t("dash.positions")}</div>
          <div style={metricValue}>{posCount}</div>
          <div style={{ fontSize: "12px", color: "#999", marginTop: "2px" }}>{t("common.stocks")}</div>
        </div>
      </div>

      {/* Row 2: Portfolio Composition + Signal Overview */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>

        {/* Portfolio Composition */}
        <div style={card()}>
          <h3 style={{ margin: "0 0 16px", fontSize: "15px", fontWeight: 700 }}>{t("dash.portfolioComposition")}</h3>
          <div style={{ display: "flex", gap: "16px", alignItems: "center", marginBottom: "16px" }}>
            {/* Cash vs Invested bar */}
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", height: "24px", borderRadius: "12px", overflow: "hidden", background: "#f0f0f0" }}>
                <div style={{ width: `${100 - cashRatio}%`, background: "#1a1a2e", transition: "width 0.3s" }} />
                <div style={{ width: `${cashRatio}%`, background: "#e2e8f0", transition: "width 0.3s" }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#888", marginTop: "4px" }}>
                <span>{t("dash.invested")} {(100 - cashRatio).toFixed(0)}%</span>
                <span>{t("dash.cash")} {cashRatio.toFixed(0)}%</span>
              </div>
            </div>
          </div>

          {/* Position breakdown */}
          {equityData.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {equityData.map((p) => (
                <div key={p.name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid #f5f5f5" }}>
                  <span style={{ fontSize: "13px", fontWeight: 600 }}>{p.name}</span>
                  <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
                    <span style={{ fontSize: "13px" }}>{fmt(p.value)}{t("common.won")}</span>
                    <span style={{ fontSize: "12px", fontWeight: 700, color: p.pnl >= 0 ? "#16a34a" : "#dc2626", minWidth: "60px", textAlign: "right" }}>
                      {p.pnl >= 0 ? "+" : ""}{p.pnl.toFixed(2)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: "#bbb", fontSize: "13px", textAlign: "center", padding: "20px" }}>
              {t("dash.noPositions")}
            </div>
          )}
        </div>

        {/* Signal Overview */}
        <div style={card()}>
          <h3 style={{ margin: "0 0 16px", fontSize: "15px", fontWeight: 700 }}>{t("dash.strategySignals")}</h3>
          <div style={{ display: "flex", gap: "20px", marginBottom: "16px" }}>
            <ResponsiveContainer width="40%" height={120}>
              <BarChart data={signalChartData}>
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {signalChartData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Bar>
                <XAxis dataKey="name" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip />
              </BarChart>
            </ResponsiveContainer>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: "8px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px" }}>
                <span style={{ color: "#16a34a", fontWeight: 700 }}>BUY</span>
                <span style={{ fontWeight: 700 }}>{buySignals.length}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px" }}>
                <span style={{ color: "#dc2626", fontWeight: 700 }}>SELL</span>
                <span style={{ fontWeight: 700 }}>{sellSignals.length}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px" }}>
                <span style={{ color: "#94a3b8", fontWeight: 700 }}>HOLD</span>
                <span style={{ fontWeight: 700 }}>{signals.length - buySignals.length - sellSignals.length}</span>
              </div>
            </div>
          </div>

          {/* Action signals only */}
          {(buySignals.length > 0 || sellSignals.length > 0) && (
            <div style={{ borderTop: "1px solid #f0f0f0", paddingTop: "12px" }}>
              <div style={{ fontSize: "12px", color: "#888", marginBottom: "8px" }}>{t("dash.actionSignals")}</div>
              {[...buySignals, ...sellSignals].slice(0, 5).map((s) => (
                <div key={s.stock_code} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", fontSize: "13px" }}>
                  <span style={{ fontWeight: 600 }}>{s.stock_code}</span>
                  <span style={{ fontWeight: 700, color: s.signal === "BUY" ? "#16a34a" : "#dc2626" }}>{s.signal}</span>
                  <span style={{ color: "#888", fontSize: "12px" }}>{s.reasons[0]?.split(":")[0] || ""}</span>
                  <span style={{ fontSize: "12px" }}>{(s.strength * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Risk + System */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "16px" }}>

        {/* Risk Gauge */}
        <div style={card()}>
          <h3 style={{ margin: "0 0 12px", fontSize: "15px", fontWeight: 700 }}>{t("dash.riskStatus")}</h3>
          <RiskMeter label={t("risk.dailyLossLimit")} used={Math.abs(dailyPnl / totalValue * 100)} max={2} unit="%" />
          <RiskMeter label={t("risk.maxDrawdown")} used={Math.abs(mdd)} max={10} unit="%" />
          <RiskMeter label={t("risk.cashRatio")} used={cashRatio} max={100} unit="%" inverted />
        </div>

        {/* System Health */}
        <div style={card()}>
          <h3 style={{ margin: "0 0 12px", fontSize: "15px", fontWeight: 700 }}>{t("dash.systemStatus")}</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <StatusRow label="API Server" ok={health?.status === "ok"} />
            <StatusRow label="Database" ok={health?.db === "ok"} />
            <StatusRow label="Redis Cache" ok={health?.redis === "ok"} />
            <StatusRow label="Tunnel" ok={true} detail="alphatrade.visualfactory.ai" />
          </div>
        </div>

        {/* Quick Actions */}
        <div style={card()}>
          <h3 style={{ margin: "0 0 12px", fontSize: "15px", fontWeight: 700 }}>{t("dash.quickActions")}</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <ActionButton label={t("action.runCycle")} color="#1a1a2e" onClick={() => apiPost("/trading/run-cycle")} />
            <ActionButton label={t("action.morningScan")} color="#7c3aed" onClick={() => apiPost("/scanner/morning")} />
            <ActionButton label={t("action.saveSnapshot")} color="#0891b2" onClick={() => apiPost("/trading/snapshot")} />
            <ActionButton label={t("action.monitorPositions")} color="#d97706" onClick={() => apiPost("/trading/monitor")} />
          </div>
        </div>
      </div>

      {/* Row 4: Top Movers */}
      {portfolio && portfolio.positions.length > 0 && (
        <div style={card()}>
          <h3 style={{ margin: "0 0 12px", fontSize: "15px", fontWeight: 700 }}>{t("dash.positionDetail")}</h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #eee", textAlign: "left" }}>
                <th style={{ padding: "8px" }}>{t("th.code")}</th>
                <th style={{ padding: "8px" }}>{t("th.name")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.qty")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.avgPrice")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.current")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.pnl")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.weight")}</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.stock_code} style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <td style={{ padding: "8px", fontWeight: 600 }}>{p.stock_code}</td>
                  <td style={{ padding: "8px" }}>{p.stock_name || "-"}</td>
                  <td style={{ padding: "8px", textAlign: "right" }}>{p.quantity}</td>
                  <td style={{ padding: "8px", textAlign: "right" }}>{fmt(p.avg_price)}</td>
                  <td style={{ padding: "8px", textAlign: "right" }}>{p.current_price ? fmt(p.current_price) : "-"}</td>
                  <td style={{ padding: "8px", textAlign: "right", color: (p.unrealized_pnl_pct ?? 0) >= 0 ? "#16a34a" : "#dc2626", fontWeight: 700 }}>
                    {p.unrealized_pnl_pct != null ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct}%` : "-"}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right" }}>{p.weight ? `${(p.weight * 100).toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Helper components

function fmt(n: number) {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

function RiskMeter({ label, used, max, unit, inverted }: { label: string; used: number; max: number; unit: string; inverted?: boolean }) {
  const pct = Math.min((used / max) * 100, 100);
  const danger = inverted ? pct < 20 : pct > 70;
  const warning = inverted ? pct < 40 : pct > 50;
  const color = danger ? "#dc2626" : warning ? "#f59e0b" : "#16a34a";

  return (
    <div style={{ marginBottom: "12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "4px" }}>
        <span style={{ color: "#666" }}>{label}</span>
        <span style={{ fontWeight: 600, color }}>{used.toFixed(1)}{unit} / {max}{unit}</span>
      </div>
      <div style={{ height: "6px", borderRadius: "3px", background: "#f0f0f0" }}>
        <div style={{ height: "100%", borderRadius: "3px", background: color, width: `${pct}%`, transition: "width 0.3s" }} />
      </div>
    </div>
  );
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <div style={{ width: "10px", height: "10px", borderRadius: "50%", background: ok ? "#16a34a" : "#dc2626", flexShrink: 0 }} />
      <span style={{ fontSize: "13px", fontWeight: 500 }}>{label}</span>
      {detail && <span style={{ fontSize: "11px", color: "#888", marginLeft: "auto" }}>{detail}</span>}
    </div>
  );
}

function ActionButton({ label, color, onClick }: { label: string; color: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "10px 16px",
        background: color,
        color: "#fff",
        border: "none",
        borderRadius: "8px",
        cursor: "pointer",
        fontSize: "13px",
        fontWeight: 600,
        textAlign: "left",
        transition: "opacity 0.2s",
      }}
      onMouseOver={(e) => (e.currentTarget.style.opacity = "0.85")}
      onMouseOut={(e) => (e.currentTarget.style.opacity = "1")}
    >
      {label}
    </button>
  );
}
