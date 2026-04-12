import { useEffect, useState } from "react";
import { XAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts";
import DirectionValue from "../components/DirectionValue";
import StrategySelector from "../components/StrategySelector";
import { apiGet, apiPost } from "../hooks/useApi";
import type { BatchSignalResult, PortfolioStatus, StrategySignal } from "../types";

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
      .then(([p, s, sig, h]) => { setPortfolio(p); setStatus(s); setSignals(sig.signals || []); setHealth(h); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-secondary p-xl">{t("common.loading")}</p>;

  const totalValue = portfolio?.total_value ?? 0;
  const totalReturn = status?.cumulative_return_pct ?? 0;
  const dailyPnl = status?.daily_pnl || 0;
  const cash = portfolio?.cash ?? 0;
  const cashRatio = totalValue > 0 ? (cash / totalValue) * 100 : 100;
  const mdd = status?.mdd_pct || 0;
  const posCount = portfolio?.positions_count || 0;

  const buySignals = signals.filter((s) => s.signal === "BUY");
  const sellSignals = signals.filter((s) => s.signal === "SELL");

  const equityData = portfolio?.positions.map((p) => ({
    name: p.stock_name || p.stock_code,
    value: (p.current_price || p.avg_price) * p.quantity,
    pnl: p.unrealized_pnl_pct || 0,
  })) || [];

  const signalDist = signals.reduce((acc, s) => { acc[s.signal] = (acc[s.signal] || 0) + 1; return acc; }, {} as Record<string, number>);
  const signalChartData = [
    { name: t("signal.buy"), count: signalDist["BUY"] || 0, color: "var(--color-buy)" },
    { name: t("signal.hold"), count: signalDist["HOLD"] || 0, color: "var(--color-hold)" },
    { name: t("signal.sell"), count: signalDist["SELL"] || 0, color: "var(--color-sell)" },
  ];

  return (
    <div className="page-content">
      {/* Row 1: Key Metrics */}
      <div className="metrics-grid metrics-grid-5">
        <div className="card">
          <div className="metric-label">{t("dash.totalValue")}</div>
          <div className="metric-value">{fmt(totalValue)}</div>
          <div className="metric-unit">{t("common.won")}</div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.dailyPnl")}</div>
          <div className={"metric-value " + (dailyPnl >= 0 ? "text-profit" : "text-loss")}>
            <DirectionValue value={dailyPnl} precision={0} />
          </div>
          <div className="metric-unit">{t("common.won")}</div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.return")}</div>
          <div className={"metric-value " + (totalReturn >= 0 ? "text-profit" : "text-loss")}>
            <DirectionValue value={totalReturn} suffix="%" />
          </div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.mdd")}</div>
          <div className={"metric-value " + (mdd < -3 ? "text-loss" : "text-warning")}>
            {mdd.toFixed(2)}%
          </div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.positions")}</div>
          <div className="metric-value">{posCount}</div>
          <div className="metric-unit">{t("common.stocks")}</div>
        </div>
      </div>

      {/* Row 2: Portfolio + Signals */}
      <div className="metrics-grid metrics-grid-2">
        <div className="card">
          <h3 className="card-title">{t("dash.portfolioComposition")}</h3>
          <div className="flex gap-lg items-center mb-lg">
            <div className="flex-1">
              <div className="cash-bar">
                <div style={{ width: `${100 - cashRatio}%`, background: "var(--color-accent)" }} />
                <div style={{ width: `${cashRatio}%`, background: "#e2e8f0" }} />
              </div>
              <div className="flex justify-between text-secondary" style={{ fontSize: "11px", marginTop: "4px" }}>
                <span>{t("dash.invested")} {(100 - cashRatio).toFixed(0)}%</span>
                <span>{t("dash.cash")} {cashRatio.toFixed(0)}%</span>
              </div>
            </div>
          </div>
          {equityData.length > 0 ? (
            <div className="flex-col gap-sm">
              {equityData.map((p) => (
                <div key={p.name} className="position-row">
                  <span className="font-bold">{p.name}</span>
                  <div className="flex gap-lg items-center">
                    <span>{fmt(p.value)}{t("common.won")}</span>
                    <span className={"font-heavy " + (p.pnl >= 0 ? "text-profit" : "text-loss")} style={{ minWidth: "60px", textAlign: "right" }}>
                      <DirectionValue value={p.pnl} suffix="%" />
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-muted text-center p-xl">{t("dash.noPositions")}</div>
          )}
        </div>

        <div className="card">
          <h3 className="card-title">{t("dash.strategySignals")}</h3>
          <div className="flex gap-xl mb-lg">
            <ResponsiveContainer width="40%" height={120}>
              <BarChart data={signalChartData}>
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {signalChartData.map((entry, i) => (<Cell key={i} fill={entry.color} />))}
                </Bar>
                <XAxis dataKey="name" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip />
              </BarChart>
            </ResponsiveContainer>
            <div className="flex-1 flex flex-col justify-center gap-sm">
              <div className="flex justify-between"><span className="text-profit font-heavy">{t("signal.buy")}</span><span className="font-heavy">{buySignals.length}</span></div>
              <div className="flex justify-between"><span className="text-loss font-heavy">{t("signal.sell")}</span><span className="font-heavy">{sellSignals.length}</span></div>
              <div className="flex justify-between"><span className="text-neutral font-heavy">{t("signal.hold")}</span><span className="font-heavy">{signals.length - buySignals.length - sellSignals.length}</span></div>
            </div>
          </div>
          {(buySignals.length > 0 || sellSignals.length > 0) && (
            <div className="action-section">
              <div className="text-secondary mb-sm" style={{ fontSize: "12px" }}>{t("dash.actionSignals")}</div>
              {[...buySignals, ...sellSignals].slice(0, 5).map((s) => (
                <div key={s.stock_code} className="signal-row">
                  <span className="font-bold">{s.stock_code}</span>
                  <span className={"font-heavy " + (s.signal === "BUY" ? "text-profit" : "text-loss")}>{t(s.signal === "BUY" ? "signal.buy" : "signal.sell")}</span>
                  <span className="text-secondary" style={{ fontSize: "12px" }}>{s.reasons[0]?.split(":")[0] || ""}</span>
                  <span style={{ fontSize: "12px" }}>{(s.strength * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Risk + System + Actions */}
      <div className="metrics-grid metrics-grid-3">
        <div className="card">
          <h3 className="card-title">{t("dash.riskStatus")}</h3>
          <RiskMeter label={t("risk.dailyLossLimit")} used={totalValue > 0 ? Math.abs(dailyPnl / totalValue * 100) : 0} max={2} unit="%" />
          <RiskMeter label={t("risk.maxDrawdown")} used={Math.abs(mdd)} max={10} unit="%" />
          <RiskMeter label={t("risk.cashRatio")} used={cashRatio} max={100} unit="%" inverted />
        </div>
        <div className="card">
          <h3 className="card-title">{t("dash.systemStatus")}</h3>
          <div className="flex flex-col gap-md">
            <StatusRow label={t("sys.apiServer")} ok={health?.status === "ok"} />
            <StatusRow label={t("sys.database")} ok={health?.db === "ok"} />
            <StatusRow label={t("sys.redisCache")} ok={health?.redis === "ok"} />
            <StatusRow label={t("sys.tunnel")} ok={true} detail="alphatrade.visualfactory.ai" />
          </div>
        </div>
        <div className="card">
          <h3 className="card-title">{t("dash.quickActions")}</h3>
          <div className="flex flex-col gap-sm">
            <button className="action-btn" style={{ background: "var(--color-accent)" }} onClick={() => apiPost("/trading/run-cycle")}>{t("action.runCycle")}</button>
            <button className="action-btn" style={{ background: "var(--color-accent-purple)" }} onClick={() => apiPost("/scanner/morning")}>{t("action.morningScan")}</button>
            <button className="action-btn" style={{ background: "var(--color-accent-cyan)" }} onClick={() => apiPost("/trading/snapshot")}>{t("action.saveSnapshot")}</button>
            <button className="action-btn" style={{ background: "var(--color-accent-amber)" }} onClick={() => apiPost("/trading/monitor")}>{t("action.monitorPositions")}</button>
            <button
              className="action-btn"
              style={{ background: "var(--color-loss)", marginTop: "8px" }}
              onClick={() => { if (confirm("킬 스위치를 활성화하면 모든 신규 주문이 차단됩니다. 계속?")) apiPost("/trading/kill-switch/activate"); }}
            >🚨 {t("command.killSwitch")}</button>
          </div>
        </div>
      </div>

      {/* Row 4: Position Detail */}
      {portfolio && portfolio.positions.length > 0 && (
        <div className="card">
          <h3 className="card-title">{t("dash.positionDetail")}</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("th.code")}</th>
                <th>{t("th.name")}</th>
                <th className="text-right">{t("th.qty")}</th>
                <th className="text-right">{t("th.avgPrice")}</th>
                <th className="text-right">{t("th.current")}</th>
                <th className="text-right">{t("th.pnl")}</th>
                <th className="text-right">{t("th.weight")}</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.stock_code}>
                  <td className="font-bold">{p.stock_code}</td>
                  <td>{p.stock_name || "-"}</td>
                  <td className="text-right">{p.quantity}</td>
                  <td className="text-right">{fmt(p.avg_price)}</td>
                  <td className="text-right">{p.current_price ? fmt(p.current_price) : "-"}</td>
                  <td className={"text-right font-heavy " + ((p.unrealized_pnl_pct ?? 0) >= 0 ? "text-profit" : "text-loss")}>
                    {p.unrealized_pnl_pct != null ? <DirectionValue value={p.unrealized_pnl_pct} suffix="%" /> : "-"}
                  </td>
                  <td className="text-right">{p.weight ? `${(p.weight * 100).toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Row 5: Strategy Selector */}
      <StrategySelector t={t} />
    </div>
  );
}

function fmt(n: number | null | undefined) {
  if (n == null || isNaN(n)) return "0";
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

function RiskMeter({ label, used, max, unit, inverted }: { label: string; used: number; max: number; unit: string; inverted?: boolean }) {
  const pct = Math.min((used / max) * 100, 100);
  const danger = inverted ? pct < 20 : pct > 70;
  const warning = inverted ? pct < 40 : pct > 50;
  const color = danger ? "var(--color-loss)" : warning ? "var(--color-warning)" : "var(--color-profit)";
  return (
    <div className="risk-meter">
      <div className="risk-meter-header">
        <span className="text-secondary">{label}</span>
        <span className="font-bold" style={{ color }}>{used.toFixed(1)}{unit} / {max}{unit}</span>
      </div>
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{ background: color, width: `${pct}%` }} />
      </div>
    </div>
  );
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  return (
    <div className="status-row">
      <span className={"status-dot " + (ok ? "ok" : "error")} />
      <span className="label">{label}</span>
      {detail && <span className="detail">{detail}</span>}
    </div>
  );
}
