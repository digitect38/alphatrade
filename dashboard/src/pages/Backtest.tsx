import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import StockSearch from "../components/StockSearch";
import { apiPost } from "../hooks/useApi";

const card = { background: "#fff", borderRadius: "8px", padding: "20px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" } as const;

interface BacktestTrade {
  date: string;
  action: "BUY" | "SELL";
  price: number;
  quantity: number;
  pnl: number | null;
}

interface BacktestResult {
  stock_code: string;
  strategy: string;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  annual_return: number | null;
  max_drawdown: number;
  sharpe_ratio: number | null;
  win_rate: number;
  total_trades: number;
  trades: BacktestTrade[];
  equity_curve: number[];
  computed_at: string;
}

const strategyKeys: Record<string, string> = {
  ensemble: "bt.ensemble",
  momentum: "bt.momentum",
  mean_reversion: "bt.meanReversion",
};

export default function BacktestPage({ t: _t }: { t: (k: string) => string }) {
  const [stockCode, setStockCode] = useState("005930");
  const [strategy, setStrategy] = useState("ensemble");
  const [capital, setCapital] = useState(10000000);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);

  const runBacktest = async () => {
    setLoading(true);
    setResult(null);
    try {
      const res = await apiPost<BacktestResult>("/strategy/backtest", {
        stock_code: stockCode, strategy, initial_capital: capital,
      });
      setResult(res);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const equityData = result?.equity_curve.map((v, i) => ({
    day: i + 1,
    equity: v,
    initial: result.initial_capital,
  })) || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Controls */}
      <div style={{ ...card, display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
        <StockSearch
          value={stockCode}
          onChange={(code) => setStockCode(code)}
          placeholder={_t("common.placeholder.stockCode")}
        />
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          style={{ padding: "8px 12px", border: "1px solid #ddd", borderRadius: "6px", fontSize: "14px" }}
        >
          {Object.keys(strategyKeys).map((k) => (
            <option key={k} value={k}>{_t(strategyKeys[k])}</option>
          ))}
        </select>
        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            step={1000000}
            min={1000000}
            style={{ padding: "8px 12px", border: "1px solid #ddd", borderRadius: "6px", fontSize: "14px", width: "140px" }}
          />
          <span style={{ fontSize: "13px", color: "#888" }}>{_t("common.won")}</span>
        </div>
        <button
          onClick={runBacktest}
          disabled={loading}
          style={{ padding: "8px 24px", background: "#1a1a2e", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "14px" }}
        >
          {loading ? _t("bt.running") : _t("bt.run")}
        </button>
      </div>

      {result && (
        <>
          {/* Performance Summary */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px" }}>
            <MetricCard
              label={_t("bt.totalReturn")}
              value={`${result.total_return >= 0 ? "+" : ""}${result.total_return}%`}
              color={result.total_return >= 0 ? "#16a34a" : "#dc2626"}
            />
            <MetricCard
              label={_t("bt.mdd")}
              value={`${result.max_drawdown}%`}
              color="#dc2626"
            />
            <MetricCard
              label={_t("bt.winRate")}
              value={`${result.win_rate}%`}
              color={result.win_rate >= 50 ? "#16a34a" : "#f59e0b"}
            />
            <MetricCard
              label={_t("bt.sharpe")}
              value={result.sharpe_ratio?.toFixed(2) ?? "-"}
              color={result.sharpe_ratio && result.sharpe_ratio > 1 ? "#16a34a" : "#888"}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px" }}>
            <MetricCard label={_t("bt.initialCapital")} value={`${result.initial_capital.toLocaleString()}${_t("common.won")}`} />
            <MetricCard label={_t("bt.finalCapital")} value={`${result.final_capital.toLocaleString()}${_t("common.won")}`} color={result.final_capital >= result.initial_capital ? "#16a34a" : "#dc2626"} />
            <MetricCard label={_t("bt.annualReturn")} value={result.annual_return != null ? `${result.annual_return}%` : "-"} />
            <MetricCard label={_t("bt.totalTrades")} value={`${result.total_trades}`} />
          </div>

          {/* Equity Curve */}
          {equityData.length > 0 && (
            <div style={card}>
              <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("bt.equityCurve")}</h3>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={equityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="day" fontSize={11} label={{ value: "일", position: "insideBottomRight", offset: -5 }} />
                  <YAxis fontSize={11} tickFormatter={(v: number) => `${(v / 10000).toFixed(0)}만`} />
                  <Tooltip formatter={(v: number) => [`${v.toLocaleString()}원`, "자산"]} />
                  <ReferenceLine y={result.initial_capital} stroke="#888" strokeDasharray="3 3" label="초기자본" />
                  <Line type="monotone" dataKey="equity" stroke="#1a1a2e" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Trade History */}
          {result.trades.length > 0 && (
            <div style={card}>
              <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("bt.tradeHistory")} ({result.trades.length})</h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #eee", textAlign: "left" }}>
                    <th style={{ padding: "8px" }}>{_t("th.date")}</th>
                    <th style={{ padding: "8px" }}>{_t("th.action")}</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>{_t("th.price")}</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>{_t("th.qty")}</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>{_t("th.pnl")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid #f0f0f0" }}>
                      <td style={{ padding: "8px", fontSize: "12px" }}>{t.date}</td>
                      <td style={{ padding: "8px", fontWeight: 700, color: t.action === "BUY" ? "#dc2626" : "#3b82f6" }}>
                        {t.action}
                      </td>
                      <td style={{ padding: "8px", textAlign: "right" }}>{t.price.toLocaleString()}</td>
                      <td style={{ padding: "8px", textAlign: "right" }}>{t.quantity}</td>
                      <td style={{ padding: "8px", textAlign: "right", fontWeight: 600, color: t.pnl != null ? (t.pnl >= 0 ? "#16a34a" : "#dc2626") : "#888" }}>
                        {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toLocaleString()}원` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={card}>
      <div style={{ fontSize: "12px", color: "#888", marginBottom: "4px" }}>{label}</div>
      <div style={{ fontSize: "20px", fontWeight: 700, color: color || "#1a1a2e" }}>{value}</div>
    </div>
  );
}
