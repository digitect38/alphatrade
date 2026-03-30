import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import StockSearch from "../components/StockSearch";
import { apiPost } from "../hooks/useApi";

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
    <div className="page-content">
      {/* Controls */}
      <div className="card flex gap-md items-center flex-wrap">
        <StockSearch
          value={stockCode}
          onChange={(code) => setStockCode(code)}
          placeholder={_t("common.placeholder.stockCode")}
        />
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          className="select"
        >
          {Object.keys(strategyKeys).map((k) => (
            <option key={k} value={k}>{_t(strategyKeys[k])}</option>
          ))}
        </select>
        <div className="flex items-center gap-xs">
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            step={1000000}
            min={1000000}
            className="input"
            style={{ width: "140px" }}
          />
          <span className="text-secondary" style={{ fontSize: "13px" }}>{_t("common.won")}</span>
        </div>
        <button onClick={runBacktest} disabled={loading} className="btn btn-primary">
          {loading ? _t("bt.running") : _t("bt.run")}
        </button>
      </div>

      {result && (
        <>
          {/* Performance Summary */}
          <div className="metrics-grid metrics-grid-4">
            <MetricCard
              label={_t("bt.totalReturn")}
              value={`${result.total_return >= 0 ? "+" : ""}${result.total_return}%`}
              colorClass={result.total_return >= 0 ? "text-profit" : "text-loss"}
            />
            <MetricCard
              label={_t("bt.mdd")}
              value={`${result.max_drawdown}%`}
              colorClass="text-loss"
            />
            <MetricCard
              label={_t("bt.winRate")}
              value={`${result.win_rate}%`}
              colorClass={result.win_rate >= 50 ? "text-profit" : "text-warning"}
            />
            <MetricCard
              label={_t("bt.sharpe")}
              value={result.sharpe_ratio?.toFixed(2) ?? "-"}
              colorClass={result.sharpe_ratio && result.sharpe_ratio > 1 ? "text-profit" : "text-neutral"}
            />
          </div>

          <div className="metrics-grid metrics-grid-4">
            <MetricCard label={_t("bt.initialCapital")} value={`${result.initial_capital.toLocaleString()}${_t("common.won")}`} />
            <MetricCard label={_t("bt.finalCapital")} value={`${result.final_capital.toLocaleString()}${_t("common.won")}`} colorClass={result.final_capital >= result.initial_capital ? "text-profit" : "text-loss"} />
            <MetricCard label={_t("bt.annualReturn")} value={result.annual_return != null ? `${result.annual_return}%` : "-"} />
            <MetricCard label={_t("bt.totalTrades")} value={`${result.total_trades}`} />
          </div>

          {/* Equity Curve */}
          {equityData.length > 0 && (
            <div className="card">
              <h3 className="card-title">{_t("bt.equityCurve")}</h3>
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
            <div className="card">
              <h3 className="card-title">{_t("bt.tradeHistory")} ({result.trades.length})</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{_t("th.date")}</th>
                    <th>{_t("th.action")}</th>
                    <th className="text-right">{_t("th.price")}</th>
                    <th className="text-right">{_t("th.qty")}</th>
                    <th className="text-right">{_t("th.pnl")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i}>
                      <td style={{ fontSize: "12px" }}>{t.date}</td>
                      <td className={"font-heavy " + (t.action === "BUY" ? "text-up" : "text-down")}>
                        {t.action}
                      </td>
                      <td className="text-right">{t.price.toLocaleString()}</td>
                      <td className="text-right">{t.quantity}</td>
                      <td className={"text-right font-bold " + (t.pnl != null ? (t.pnl >= 0 ? "text-profit" : "text-loss") : "text-neutral")}>
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

function MetricCard({ label, value, colorClass }: { label: string; value: string; colorClass?: string }) {
  return (
    <div className="card">
      <div className="metric-label">{label}</div>
      <div className={"metric-value " + (colorClass || "")}>{value}</div>
    </div>
  );
}
