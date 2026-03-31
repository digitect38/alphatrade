import { useEffect, useState } from "react";
import { apiGet } from "../hooks/useApi";

interface PnLPosition {
  stock_code: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
  weight: number;
  current_value: number;
}

interface PnLData {
  total_value: number;
  total_invested: number;
  cash: number;
  total_unrealized_pnl: number;
  total_unrealized_pct: number;
  daily_pnl: number;
  daily_return_pct: number;
  positions_count: number;
  positions: PnLPosition[];
}

interface VaRLevel {
  var_pct: number;
  var_amount: number;
  cvar_pct: number;
  cvar_amount: number;
}

interface VaRData {
  total_value: number;
  var: Record<string, VaRLevel>;
  marginal_var: { stock_code: string; weight_pct: number; beta: number; component_var: number; pct_of_portfolio_var: number }[];
  risk_metrics: {
    annualized_volatility_pct: number;
    annualized_return_pct: number;
    sharpe_ratio: number;
    max_daily_loss_pct: number;
    skewness: number;
    excess_kurtosis: number;
  };
  message?: string;
}

interface StressScenario {
  scenario_key: string;
  scenario_name: string;
  description: string;
  market_shock_pct: number;
  portfolio_impact_pct: number;
  portfolio_impact_amount: number;
  stressed_total_value: number;
  position_impacts: { stock_code: string; stock_name: string; sector: string; shock_pct: number; impact_amount: number }[];
}

interface StressData {
  portfolio: { total_value: number; cash: number; invested: number; positions_count: number };
  worst_scenario: { name: string; impact_pct: number; impact_amount: number };
  scenarios: StressScenario[];
  message?: string;
}

interface PreLaunchCheck {
  name: string;
  status: "PASS" | "FAIL" | "WARN" | "INFO";
  detail: string;
}

interface PreLaunchData {
  overall: string;
  fail_count: number;
  warn_count: number;
  checks: PreLaunchCheck[];
  kis_mode: string;
}

type Tab = "pnl" | "var" | "stress" | "prelaunch";

export default function RiskPage({ t: _t }: { t: (k: string) => string }) {
  const [tab, setTab] = useState<Tab>("pnl");
  const [pnl, setPnl] = useState<PnLData | null>(null);
  const [varData, setVarData] = useState<VaRData | null>(null);
  const [stress, setStress] = useState<StressData | null>(null);
  const [prelaunch, setPrelaunch] = useState<PreLaunchData | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async (t: Tab) => {
    setLoading(true);
    try {
      if (t === "pnl") setPnl(await apiGet<PnLData>("/risk/pnl"));
      else if (t === "var") setVarData(await apiGet<VaRData>("/risk/var"));
      else if (t === "stress") setStress(await apiGet<StressData>("/risk/stress-test"));
      else if (t === "prelaunch") setPrelaunch(await apiGet<PreLaunchData>("/trading/pre-launch-check"));
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { void load(tab); }, [tab]);

  const tabs: { key: Tab; label: string }[] = [
    { key: "pnl", label: _t("risk.pnl") },
    { key: "var", label: _t("risk.var") },
    { key: "stress", label: _t("risk.stress") },
    { key: "prelaunch", label: _t("risk.prelaunch") },
  ];

  return (
    <div className="page-content">
      <div className="card">
        <div className="asset-range-group" style={{ marginBottom: 12 }}>
          {tabs.map((t) => (
            <button key={t.key} className={`asset-range-chip ${tab === t.key ? "is-active" : ""}`} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
        {loading && <span className="analysis-loading-state">{_t("common.loading")}</span>}
      </div>

      {tab === "pnl" && pnl && <PnLView data={pnl} t={_t} />}
      {tab === "var" && varData && <VaRView data={varData} t={_t} />}
      {tab === "stress" && stress && <StressView data={stress} t={_t} />}
      {tab === "prelaunch" && prelaunch && <PreLaunchView data={prelaunch} t={_t} />}
    </div>
  );
}

function PnLView({ data, t: _t }: { data: PnLData; t: (k: string) => string }) {
  return (
    <>
      <div className="card">
        <h3 className="card-title">{_t("risk.portfolioSummary")}</h3>
        <div className="metrics-grid metrics-grid-4">
          <div><div className="metric-label">{_t("risk.totalValue")}</div><div className="font-bold">{data.total_value.toLocaleString()}{_t("common.won")}</div></div>
          <div><div className="metric-label">{_t("risk.cash")}</div><div className="font-bold">{data.cash.toLocaleString()}{_t("common.won")}</div></div>
          <div>
            <div className="metric-label">{_t("risk.unrealizedPnl")}</div>
            <div className={`font-bold ${data.total_unrealized_pnl >= 0 ? "text-profit" : "text-loss"}`}>
              {data.total_unrealized_pnl >= 0 ? "+" : ""}{data.total_unrealized_pnl.toLocaleString()}{_t("common.won")} ({data.total_unrealized_pct}%)
            </div>
          </div>
          <div>
            <div className="metric-label">{_t("risk.dailyPnl")}</div>
            <div className={`font-bold ${data.daily_pnl >= 0 ? "text-profit" : "text-loss"}`}>
              {data.daily_pnl >= 0 ? "+" : ""}{data.daily_pnl.toLocaleString()}{_t("common.won")} ({data.daily_return_pct}%)
            </div>
          </div>
        </div>
      </div>

      {data.positions.length > 0 && (
        <div className="card">
          <h3 className="card-title">{_t("risk.positionsPnl")} ({data.positions_count})</h3>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--color-border-light)", textAlign: "left" }}>
                  <th style={{ padding: "6px 8px" }}>{_t("common.stockCode")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.qty")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.avgPrice")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.currentPrice")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.unrealizedPnl")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.pnlPct")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.weight")}</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map((p) => (
                  <tr key={p.stock_code} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "6px 8px", fontWeight: 600 }}>{p.stock_code}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{p.quantity}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{p.avg_price.toLocaleString()}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{p.current_price.toLocaleString()}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }} className={p.unrealized_pnl >= 0 ? "text-profit" : "text-loss"}>
                      {p.unrealized_pnl >= 0 ? "+" : ""}{p.unrealized_pnl.toLocaleString()}
                    </td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }} className={p.pnl_pct >= 0 ? "text-profit" : "text-loss"}>
                      {p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct}%
                    </td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{p.weight}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function VaRView({ data, t: _t }: { data: VaRData; t: (k: string) => string }) {
  if (data.message) return <div className="card"><p>{data.message}</p></div>;
  return (
    <>
      <div className="card">
        <h3 className="card-title">{_t("risk.varTitle")}</h3>
        <div className="metrics-grid metrics-grid-4">
          {Object.entries(data.var).map(([level, v]) => (
            <div key={level} style={{ padding: 8, background: "#fef2f2", borderRadius: 8 }}>
              <div className="metric-label">VaR {level}</div>
              <div className="font-bold text-loss">{v.var_amount.toLocaleString()}{_t("common.won")}</div>
              <div style={{ fontSize: 11 }} className="text-secondary">{v.var_pct}%</div>
              <div style={{ fontSize: 11, marginTop: 4 }}>
                CVaR: <span className="text-loss">{v.cvar_amount.toLocaleString()}{_t("common.won")}</span>
              </div>
            </div>
          ))}
          {data.risk_metrics && (
            <>
              <div style={{ padding: 8 }}>
                <div className="metric-label">{_t("risk.volatility")}</div>
                <div className="font-bold">{data.risk_metrics.annualized_volatility_pct}%</div>
              </div>
              <div style={{ padding: 8 }}>
                <div className="metric-label">{_t("risk.sharpe")}</div>
                <div className="font-bold">{data.risk_metrics.sharpe_ratio}</div>
              </div>
            </>
          )}
        </div>
      </div>

      {data.marginal_var.length > 0 && (
        <div className="card">
          <h3 className="card-title">{_t("risk.marginalVar")}</h3>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--color-border-light)", textAlign: "left" }}>
                  <th style={{ padding: "6px 8px" }}>{_t("common.stockCode")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.weight")}</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Beta</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Component VaR</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>{_t("risk.contribution")}</th>
                </tr>
              </thead>
              <tbody>
                {data.marginal_var.map((m) => (
                  <tr key={m.stock_code} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "6px 8px", fontWeight: 600 }}>{m.stock_code}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{m.weight_pct}%</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{m.beta}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }} className="text-loss">{m.component_var.toLocaleString()}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>{m.pct_of_portfolio_var}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function StressView({ data, t: _t }: { data: StressData; t: (k: string) => string }) {
  if (data.message) return <div className="card"><p>{data.message}</p></div>;
  return (
    <>
      <div className="card">
        <h3 className="card-title">{_t("risk.stressTitle")}</h3>
        <div className="metrics-grid metrics-grid-4" style={{ marginBottom: 16 }}>
          <div><div className="metric-label">{_t("risk.totalValue")}</div><div className="font-bold">{data.portfolio.total_value.toLocaleString()}{_t("common.won")}</div></div>
          <div><div className="metric-label">{_t("risk.invested")}</div><div className="font-bold">{data.portfolio.invested.toLocaleString()}{_t("common.won")}</div></div>
          <div>
            <div className="metric-label">{_t("risk.worstScenario")}</div>
            <div className="font-bold text-loss">{data.worst_scenario.name}</div>
            <div style={{ fontSize: 12 }} className="text-loss">{data.worst_scenario.impact_pct}% ({data.worst_scenario.impact_amount.toLocaleString()}{_t("common.won")})</div>
          </div>
        </div>
      </div>

      {data.scenarios.map((s) => (
        <div key={s.scenario_key} className="card" style={{ marginBottom: 8 }}>
          <div className="flex items-center gap-md" style={{ marginBottom: 8 }}>
            <strong style={{ fontSize: 14 }}>{s.scenario_name}</strong>
            <span className={`font-bold ${s.portfolio_impact_pct < -10 ? "text-loss" : s.portfolio_impact_pct < -5 ? "text-warning" : "text-secondary"}`}
              style={{ fontSize: 14 }}>
              {s.portfolio_impact_pct}%
            </span>
            <span className="text-loss" style={{ fontSize: 12 }}>({s.portfolio_impact_amount.toLocaleString()}{_t("common.won")})</span>
          </div>
          <p className="text-secondary" style={{ fontSize: 12, margin: "0 0 8px" }}>{s.description}</p>
          {s.position_impacts.length > 0 && (
            <div className="flex flex-wrap gap-sm">
              {s.position_impacts.map((p) => (
                <div key={p.stock_code} style={{ fontSize: 11, padding: "4px 8px", background: p.shock_pct < 0 ? "#fef2f2" : "#f0fdf4", borderRadius: 4 }}>
                  <strong>{p.stock_name}</strong> {p.shock_pct > 0 ? "+" : ""}{p.shock_pct}% ({p.impact_amount.toLocaleString()})
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function PreLaunchView({ data, t: _t }: { data: PreLaunchData; t: (k: string) => string }) {
  const statusIcon = (s: string) => s === "PASS" ? "✅" : s === "FAIL" ? "❌" : s === "WARN" ? "⚠️" : "ℹ️";
  const overallColor = data.overall === "READY" ? "text-profit" : data.overall === "NOT_READY" ? "text-loss" : "text-warning";
  return (
    <>
      <div className="card">
        <h3 className="card-title">{_t("risk.prelaunchTitle")}</h3>
        <div className="flex items-center gap-lg" style={{ marginBottom: 16 }}>
          <div>
            <div className="metric-label">{_t("risk.overallStatus")}</div>
            <div className={`font-bold ${overallColor}`} style={{ fontSize: 20 }}>{data.overall}</div>
          </div>
          <div>
            <div className="metric-label">{_t("risk.kisMode")}</div>
            <div className="font-bold">{data.kis_mode === "live" ? "실전" : "모의투자"}</div>
          </div>
          {data.fail_count > 0 && <div className="text-loss font-bold">FAIL: {data.fail_count}</div>}
          {data.warn_count > 0 && <div className="text-warning font-bold">WARN: {data.warn_count}</div>}
        </div>
      </div>
      <div className="card">
        {data.checks.map((c, i) => (
          <div key={i} className="flex items-center gap-md" style={{ padding: "8px 0", borderBottom: i < data.checks.length - 1 ? "1px solid #f0f0f0" : "none" }}>
            <span style={{ fontSize: 18, width: 28 }}>{statusIcon(c.status)}</span>
            <span className="font-bold" style={{ fontSize: 13, minWidth: 160 }}>{c.name}</span>
            <span className="text-secondary" style={{ fontSize: 12 }}>{c.detail}</span>
          </div>
        ))}
      </div>
    </>
  );
}
