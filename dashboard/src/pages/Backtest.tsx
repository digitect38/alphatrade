import { useCallback, useEffect, useMemo, useState, type MutableRefObject, type ReactNode } from "react";
import DirectionValue from "../components/DirectionValue";
import StockSearch from "../components/StockSearch";
import { LightweightChart } from "../components/charts";
import type { OHLCVPoint, ChartMarker } from "../components/charts";
import { apiGet, apiPost } from "../hooks/useApi";

interface BacktestTrade {
  date: string;
  action: "BUY" | "SELL";
  price: number;
  quantity: number;
  pnl: number | null;
  holding_bars: number | null;
  reason: string | null;
}

interface BacktestResult {
  stock_code: string;
  strategy: string;
  initial_capital: number;
  final_capital: number;
  period_bars: number;
  total_return: number;
  benchmark_return: number | null;
  annual_return: number | null;
  max_drawdown: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  win_rate: number;
  profit_factor: number | null;
  avg_trade_pnl: number | null;
  avg_holding_bars: number | null;
  max_consecutive_losses: number;
  total_trades: number;
  expectancy: number | null;
  exposure_pct: number | null;
  statistical_warnings: string[];
  trades: BacktestTrade[];
  equity_curve: number[];
  equity_series: Array<{ time: string; equity: number; benchmark?: number; drawdown?: number }> | null;
  trade_markers: Array<{ time: string; action: string; price: number }> | null;
  monthly_returns: Array<{ month: string; return_pct: number }> | null;
  computed_at: string;
  start_date: string | null;
  end_date: string | null;
  interval: string;
}

type TradeFilter = "all" | "buys" | "sells" | "winners" | "losers";

const strategyKeys: Record<string, string> = {
  ensemble: "bt.ensemble",
  momentum: "bt.momentum",
  mean_reversion: "bt.meanReversion",
};

const tradeFilterKeys: Record<TradeFilter, string> = {
  all: "bt.tradeFilter.all",
  buys: "bt.tradeFilter.buys",
  sells: "bt.tradeFilter.sells",
  winners: "bt.tradeFilter.winners",
  losers: "bt.tradeFilter.losers",
};

const DURATION_OPTIONS: { value: string; months: number }[] = [
  { value: "3M", months: 3 },
  { value: "6M", months: 6 },
  { value: "1Y", months: 12 },
  { value: "2Y", months: 24 },
  { value: "3Y", months: 36 },
  { value: "5Y", months: 60 },
  { value: "MAX", months: 0 },
];

function calcEndDate(start: string, durationValue: string): string | undefined {
  if (durationValue === "MAX" || !start) return undefined;
  const months = DURATION_OPTIONS.find(d => d.value === durationValue)?.months || 12;
  const d = new Date(start);
  d.setMonth(d.getMonth() + months);
  return d.toISOString().slice(0, 10);
}

export default function BacktestPage({ t: _t, onStockChangeRef }: { t: (k: string) => string; onStockChangeRef?: MutableRefObject<((code: string, name: string) => void) | null> }) {
  const [stockCode, setStockCode] = useState("005930");
  const [stockName, setStockName] = useState("");
  const [strategy, setStrategy] = useState("ensemble");
  const [capital, setCapital] = useState(10000000);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [duration, setDuration] = useState("1Y");
  const [interval, setInterval] = useState("1d");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [buyFeeRate, setBuyFeeRate] = useState(0.00015);
  const [sellFeeRate, setSellFeeRate] = useState(0.00015);
  const [sellTaxRate, setSellTaxRate] = useState(0.0018);
  const [slippageRate, setSlippageRate] = useState(0.001);
  const [capitalFraction, setCapitalFraction] = useState(1.0);
  const [maxDrawdownStop, setMaxDrawdownStop] = useState(8);
  const [tradeFilter, setTradeFilter] = useState<TradeFilter>("all");
  const [benchmark, setBenchmark] = useState("buy_and_hold");
  const [errorMsg, setErrorMsg] = useState("");

  // Fetch stock name when code changes
  useEffect(() => {
    if (!/^\d{6}$/.test(stockCode)) return;
    apiGet<{ stock_name: string }>(`/asset/${stockCode}/overview`)
      .then((d) => { if (d.stock_name) setStockName(d.stock_name); })
      .catch(() => {});
  }, [stockCode]);

  // Run backtest for a given stock code
  const runBacktestForCode = (code: string) => {
    setLoading(true);
    setResult(null);
    apiPost<BacktestResult>("/strategy/backtest", {
      stock_code: code, strategy, initial_capital: capital, interval,
      start_date: startDate || undefined, end_date: calcEndDate(startDate, duration),
      buy_fee_rate: buyFeeRate, sell_fee_rate: sellFeeRate, sell_tax_rate: sellTaxRate,
      slippage_rate: slippageRate, capital_fraction: capitalFraction,
      max_drawdown_stop: maxDrawdownStop / 100,
      benchmark,
    }).then(setResult).catch(() => {}).finally(() => setLoading(false));
  };

  // Register callback so sidebar can change stock on this page
  if (onStockChangeRef) {
    onStockChangeRef.current = (code, name) => {
      setStockCode(code);
      setStockName(name);
      if (result) runBacktestForCode(code);
    };
  }

  const runBacktest = useCallback(async () => {
    const computedEnd = calcEndDate(startDate, duration);
    if (startDate && computedEnd && startDate > computedEnd) {
      setErrorMsg("시작일이 유효하지 않습니다.");
      return;
    }
    
    setErrorMsg("");
    setLoading(true);
    setResult(null);
    try {
      const res = await apiPost<BacktestResult>("/strategy/backtest", {
        stock_code: stockCode,
        strategy,
        initial_capital: capital,
        interval,
        start_date: startDate || undefined,
        end_date: calcEndDate(startDate, duration),
        buy_fee_rate: buyFeeRate,
        sell_fee_rate: sellFeeRate,
        sell_tax_rate: sellTaxRate,
        slippage_rate: slippageRate,
        capital_fraction: capitalFraction,
        max_drawdown_stop: maxDrawdownStop / 100,
        benchmark,
      });
      setResult(res);
    } catch (e: any) {
      setErrorMsg(e.message || String(e));
      console.error(e);
    }
    setLoading(false);
  }, [stockCode, strategy, capital, interval, startDate, duration, buyFeeRate, sellFeeRate, sellTaxRate, slippageRate, capitalFraction, maxDrawdownStop, benchmark]);

  const equityData = useMemo<OHLCVPoint[]>(() => {
    // Prefer real equity_series from API
    if (result?.equity_series?.length) {
      return result.equity_series.map(pt => ({
        time: pt.time,
        open: pt.equity, high: pt.equity, low: pt.equity, close: pt.equity, volume: 0,
      }));
    }
    // Fallback: synthetic dates from equity_curve
    if (!result?.equity_curve?.length) return [];
    const baseDate = result.computed_at ? new Date(result.computed_at) : new Date();
    baseDate.setDate(baseDate.getDate() - result.equity_curve.length);
    return result.equity_curve.map((v, i) => {
      const d = new Date(baseDate);
      d.setDate(d.getDate() + i);
      return {
        time: d.toISOString().slice(0, 10),
        open: v, high: v, low: v, close: v, volume: 0,
      };
    });
  }, [result]);

  const markers = useMemo<ChartMarker[]>(() => {
    if (!result?.trade_markers) return [];
    return result.trade_markers.map(m => ({
      time: m.time,
      label: m.action === "BUY" ? "B" : "S",
      color: m.action === "BUY" ? "#16a34a" : "#dc2626",
    }));
  }, [result]);

  const edgeVsBenchmark = result && result.benchmark_return != null
    ? result.total_return - result.benchmark_return
    : null;

  const sells = result?.trades.filter((trade) => trade.action === "SELL") ?? [];

  // Filtered trades
  const filteredTrades = useMemo(() => {
    if (!result) return [];
    const trades = result.trades;
    switch (tradeFilter) {
      case "buys": return trades.filter(t => t.action === "BUY");
      case "sells": return trades.filter(t => t.action === "SELL");
      case "winners": return trades.filter(t => t.pnl != null && t.pnl > 0);
      case "losers": return trades.filter(t => t.pnl != null && t.pnl < 0);
      default: return trades;
    }
  }, [result, tradeFilter]);

  const winCount = result?.trades.filter(t => t.pnl != null && t.pnl > 0).length ?? 0;
  const lossCount = result?.trades.filter(t => t.pnl != null && t.pnl < 0).length ?? 0;

  return (
    <div className="page-content">
      {/* Controls */}
      <div className="card flex gap-md items-center flex-wrap">
        <StockSearch
          value={stockCode}
          onChange={(code, name) => { setStockCode(code); if (name) setStockName(name); }}
          stockName={stockName}
          placeholder={_t("common.placeholder.stockCode")}
          t={_t}
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

        {/* Start date + Duration */}
        <div className="flex items-center gap-xs">
          <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.startDate")}</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="input"
            style={{ width: "140px" }}
          />
        </div>
        <div className="flex items-center gap-xs">
          <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.duration")}</label>
          <select
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            className="select"
          >
            {DURATION_OPTIONS.map((d) => (
              <option key={d.value} value={d.value}>{d.value === "MAX" ? _t("bt.durationMax") : d.value}</option>
            ))}
          </select>
        </div>

        {/* Interval */}
        <div className="flex items-center gap-xs">
          <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.interval")}</label>
          <select
            value={interval}
            onChange={(e) => setInterval(e.target.value)}
            className="select"
            style={{ width: "80px" }}
          >
            <option value="1d">1d</option>
            <option value="1m">1m</option>
          </select>
        </div>

        {/* Max DD Stop */}
        <div className="flex items-center gap-xs">
          <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.maxDdStop")}</label>
          <input
            type="number"
            value={maxDrawdownStop}
            onChange={(e) => setMaxDrawdownStop(Number(e.target.value))}
            step={1}
            min={1}
            max={50}
            className="input"
            style={{ width: "70px" }}
          />
          <span className="text-secondary" style={{ fontSize: "13px" }}>%</span>
        </div>

        {/* Benchmark */}
        <div className="flex items-center gap-xs">
          <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.benchmark")}</label>
          <select value={benchmark} onChange={(e) => setBenchmark(e.target.value)} className="select" style={{ width: "120px" }}>
            <option value="buy_and_hold">Buy & Hold</option>
            <option value="kospi">KOSPI</option>
            <option value="none">None</option>
          </select>
        </div>

        <button onClick={runBacktest} disabled={loading} className="btn btn-primary">
          {loading ? _t("bt.running") : _t("bt.run")}
        </button>
      </div>

      {errorMsg && (
        <div className="card text-loss font-bold" style={{ background: "#fef2f2", padding: "12px", borderRadius: "6px" }}>
          ⚠️ {errorMsg}
        </div>
      )}

      {/* Advanced Settings (collapsible) */}
      <div className="card">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          style={{
            background: "none", border: "none", cursor: "pointer",
            padding: 0, fontSize: "14px", fontWeight: 600,
            color: "var(--text-secondary, #666)",
          }}
        >
          {showAdvanced ? "▾" : "▸"} {_t("bt.advanced")}
        </button>
        {showAdvanced && (
          <div className="flex gap-md items-center flex-wrap" style={{ marginTop: "12px" }}>
            <div className="flex items-center gap-xs">
              <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.buyFee")}</label>
              <input
                type="number"
                value={buyFeeRate}
                onChange={(e) => setBuyFeeRate(Number(e.target.value))}
                step={0.00001}
                min={0}
                className="input"
                style={{ width: "100px" }}
              />
            </div>
            <div className="flex items-center gap-xs">
              <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.sellFee")}</label>
              <input
                type="number"
                value={sellFeeRate}
                onChange={(e) => setSellFeeRate(Number(e.target.value))}
                step={0.00001}
                min={0}
                className="input"
                style={{ width: "100px" }}
              />
            </div>
            <div className="flex items-center gap-xs">
              <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.sellTax")}</label>
              <input
                type="number"
                value={sellTaxRate}
                onChange={(e) => setSellTaxRate(Number(e.target.value))}
                step={0.0001}
                min={0}
                className="input"
                style={{ width: "100px" }}
              />
            </div>
            <div className="flex items-center gap-xs">
              <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.slippage")}</label>
              <input
                type="number"
                value={slippageRate}
                onChange={(e) => setSlippageRate(Number(e.target.value))}
                step={0.0001}
                min={0}
                className="input"
                style={{ width: "100px" }}
              />
            </div>
            <div className="flex items-center gap-xs">
              <label className="text-secondary" style={{ fontSize: "13px" }}>{_t("bt.capitalFraction")}</label>
              <input
                type="number"
                value={capitalFraction}
                onChange={(e) => setCapitalFraction(Number(e.target.value))}
                step={0.1}
                min={0.1}
                max={1.0}
                className="input"
                style={{ width: "80px" }}
              />
            </div>
          </div>
        )}
      </div>

      {result && (
        <>
          {/* Period summary banner */}
          <div className="card bt-period-banner">
            <div className="bt-period-row">
              <span className="bt-period-label">{_t("bt.periodLabel")}</span>
              <span className="bt-period-value">
                {(() => {
                  const es = result.equity_series;
                  const first = es?.[0]?.time?.slice(0, 10) || result.start_date || "—";
                  const last = es?.[es.length - 1]?.time?.slice(0, 10) || result.end_date || "—";
                  return `${first}  →  ${last}`;
                })()}
              </span>
              {(result.start_date || result.end_date) && (() => {
                const es = result.equity_series;
                const actualFirst = es?.[0]?.time?.slice(0, 10);
                const actualLast = es?.[es.length - 1]?.time?.slice(0, 10);
                const differs = (result.start_date && actualFirst && result.start_date !== actualFirst)
                  || (result.end_date && actualLast && result.end_date !== actualLast);
                return differs ? (
                  <span className="bt-period-meta">{_t("bt.requestedRange")} {result.start_date || "—"} ~ {result.end_date || "—"}</span>
                ) : null;
              })()}
              <span className="bt-period-meta">
                {result.period_bars}{_t("bt.bars")} · {result.interval} · {_t(strategyKeys[result.strategy] || "bt.ensemble")}
              </span>
              <span className="bt-period-meta">
                {_t("bt.computedAt")} {result.computed_at?.slice(0, 19).replace("T", " ")}
              </span>
            </div>
          </div>

          {result.statistical_warnings?.length > 0 && (
            <div className="card bt-warnings">
              {result.statistical_warnings.map((w, i) => (
                <div key={i} className="bt-warning-item">{w}</div>
              ))}
            </div>
          )}
          <div className="metrics-grid metrics-grid-5">
            <MetricCard
              label={_t("bt.totalReturn")}
              valueNode={<DirectionValue value={result.total_return} suffix="%" />}
              colorClass={result.total_return >= 0 ? "text-profit" : "text-loss"}
            />
            <MetricCard
              label={_t("bt.edgeVsBenchmark")}
              valueNode={edgeVsBenchmark != null ? <DirectionValue value={edgeVsBenchmark} suffix="%" /> : "-"}
              colorClass={edgeVsBenchmark != null ? (edgeVsBenchmark >= 0 ? "text-profit" : "text-loss") : "text-neutral"}
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

          {/* New metric cards: Sortino, Calmar, Expectancy, Exposure */}
          <div className="metrics-grid metrics-grid-4">
            <MetricCard
              label={_t("bt.sortino")}
              value={result.sortino_ratio?.toFixed(2) ?? "-"}
              colorClass={result.sortino_ratio && result.sortino_ratio > 1 ? "text-profit" : "text-neutral"}
            />
            <MetricCard
              label={_t("bt.calmar")}
              value={result.calmar_ratio?.toFixed(2) ?? "-"}
              colorClass={result.calmar_ratio && result.calmar_ratio > 1 ? "text-profit" : "text-neutral"}
            />
            <MetricCard
              label={_t("bt.expectancy")}
              value={result.expectancy != null ? formatWon(result.expectancy, _t) : "-"}
              colorClass={result.expectancy != null ? (result.expectancy >= 0 ? "text-profit" : "text-loss") : "text-neutral"}
            />
            <MetricCard
              label={_t("bt.exposure")}
              value={result.exposure_pct != null ? `${result.exposure_pct.toFixed(1)}%` : "-"}
            />
          </div>

          <div className="card">
            <h3 className="card-title">{_t("bt.performanceQuality")}</h3>
            <div className="metrics-grid metrics-grid-5">
              <MetricCard label={_t("bt.initialCapital")} value={formatWon(result.initial_capital, _t)} />
              <MetricCard
                label={_t("bt.finalCapital")}
                value={formatWon(result.final_capital, _t)}
                colorClass={result.final_capital >= result.initial_capital ? "text-profit" : "text-loss"}
              />
              <MetricCard label={_t("bt.annualReturn")} value={result.annual_return != null ? `${result.annual_return}%` : "-"} />
              <MetricCard label={_t("bt.benchmarkReturn")} value={result.benchmark_return != null ? `${result.benchmark_return}%` : "-"} />
              <MetricCard label={_t("bt.periodBars")} value={`${result.period_bars}`} />
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">{_t("bt.tradeDiagnostics")}</h3>
            <div className="metrics-grid metrics-grid-5">
              <MetricCard label={_t("bt.totalTrades")} value={`${result.total_trades}`} />
              <MetricCard label={_t("bt.profitFactor")} value={result.profit_factor != null ? result.profit_factor.toFixed(2) : "-"} />
              <MetricCard
                label={_t("bt.avgTradePnl")}
                value={result.avg_trade_pnl != null ? formatWon(result.avg_trade_pnl, _t) : "-"}
                colorClass={result.avg_trade_pnl != null ? (result.avg_trade_pnl >= 0 ? "text-profit" : "text-loss") : "text-neutral"}
              />
              <MetricCard label={_t("bt.avgHoldingBars")} value={result.avg_holding_bars != null ? `${result.avg_holding_bars}` : "-"} />
              <MetricCard
                label={_t("bt.lossStreak")}
                value={`${result.max_consecutive_losses}`}
                colorClass={result.max_consecutive_losses >= 3 ? "text-loss" : "text-neutral"}
              />
            </div>
          </div>

          <div className="metrics-grid metrics-grid-4">
            <MetricCard label={_t("bt.stockCode")} value={stockName ? `${stockName} (${result.stock_code})` : result.stock_code} />
            <MetricCard label={_t("bt.strategy")} value={_t(strategyKeys[result.strategy] || "bt.ensemble")} />
            <MetricCard label={_t("bt.capital")} value={formatWon(result.initial_capital, _t)} />
            <MetricCard label={_t("bt.totalTrades")} value={`${sells.length} sells / ${result.total_trades} events`} />
          </div>

          {equityData.length > 0 && (
            <div className="card">
              <h3 className="card-title">{_t("bt.equityCurve")}</h3>
              <LightweightChart
                data={equityData}
                mode="line"
                volume={false}
                height={300}
                lineColor="#1a1a2e"
                markers={markers}
              />
            </div>
          )}

          {/* Monthly Returns Heatmap */}
          {result.monthly_returns && result.monthly_returns.length > 0 && (
            <div className="card">
              <h3 className="card-title">{_t("bt.monthlyReturns")}</h3>
              <MonthlyHeatmap data={result.monthly_returns} />
            </div>
          )}

          {/* Trade History */}
          {result.trades.length > 0 && (
            <div className="card">
              <h3 className="card-title">
                {_t("bt.tradeHistory")} ({filteredTrades.length} / {result.trades.length}
                {" — "}
                {winCount}W / {lossCount}L)
              </h3>

              {/* Filter toggles */}
              <div className="flex gap-xs" style={{ marginBottom: "12px" }}>
                {(Object.keys(tradeFilterKeys) as TradeFilter[]).map(f => (
                  <button
                    key={f}
                    onClick={() => setTradeFilter(f)}
                    className={`btn ${tradeFilter === f ? "btn-primary" : ""}`}
                    style={{ fontSize: "12px", padding: "4px 10px" }}
                  >
                    {_t(tradeFilterKeys[f])}
                  </button>
                ))}
              </div>

              <table className="data-table">
                <thead>
                  <tr>
                    <th>{_t("th.date")}</th>
                    <th>{_t("th.action")}</th>
                    <th className="text-right">{_t("th.price")}</th>
                    <th className="text-right">{_t("th.qty")}</th>
                    <th className="text-right">{_t("th.holdingBars")}</th>
                    <th className="text-right">{_t("th.pnl")}</th>
                    <th>{_t("th.reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTrades.map((t, i) => (
                    <tr key={i}>
                      <td style={{ fontSize: "12px" }}>{t.date}</td>
                      <td className={"font-heavy " + (t.action === "BUY" ? "text-up" : "text-down")}>
                        {_t(t.action === "BUY" ? "signal.buy" : "signal.sell")}
                      </td>
                      <td className="text-right">{t.price.toLocaleString()}</td>
                      <td className="text-right">{t.quantity}</td>
                      <td className="text-right">{t.holding_bars ?? "-"}</td>
                      <td className={"text-right font-bold " + (t.pnl != null ? (t.pnl >= 0 ? "text-profit" : "text-loss") : "text-neutral")}>
                        {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toLocaleString()}원` : "-"}
                      </td>
                      <td style={{ fontSize: "12px" }}>{t.reason ?? "-"}</td>
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

function MetricCard({
  label,
  value,
  valueNode,
  colorClass,
}: {
  label: string;
  value?: string;
  valueNode?: ReactNode | string;
  colorClass?: string;
}) {
  return (
    <div className="card">
      <div className="metric-label">{label}</div>
      <div className={"metric-value " + (colorClass || "")}>{valueNode ?? value}</div>
    </div>
  );
}

function formatWon(value: number, t: (k: string) => string) {
  return `${Math.round(value).toLocaleString()}${t("common.won")}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function MonthlyHeatmap({ data }: { data: Array<{ month: string; return_pct: number }> }) {
  // Group by year
  const years: Record<string, (number | null)[]> = {};
  for (const d of data) {
    const [y, m] = d.month.split("-");
    if (!years[y]) years[y] = Array(12).fill(null);
    years[y][parseInt(m, 10) - 1] = d.return_pct;
  }
  const sortedYears = Object.keys(years).sort();

  const cellColor = (v: number) => {
    if (v > 5) return "#16a34a";
    if (v > 2) return "#4ade80";
    if (v > 0) return "#bbf7d0";
    if (v > -2) return "#fecaca";
    if (v > -5) return "#f87171";
    return "#dc2626";
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="data-table bt-heatmap">
        <thead>
          <tr>
            <th></th>
            {MONTHS.map(m => <th key={m}>{m}</th>)}
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {sortedYears.map(y => {
            const vals = years[y];
            // Compound return: (1+r1)(1+r2)...(1+rn) - 1
            const yearTotal = (vals.reduce<number>((acc, v) => v != null ? acc * (1 + v / 100) : acc, 1) - 1) * 100;
            return (
              <tr key={y}>
                <td style={{ fontWeight: 600 }}>{y}</td>
                {vals.map((v, mi) => (
                  <td key={mi} style={{
                    background: v != null ? cellColor(v) : "transparent",
                    color: v != null ? (Math.abs(v) > 2 ? "#fff" : "#333") : "#ccc",
                    textAlign: "center", fontSize: "12px", fontWeight: 600,
                  }}>
                    {v != null ? `${v > 0 ? "+" : ""}${v.toFixed(1)}` : ""}
                  </td>
                ))}
                <td style={{
                  background: cellColor(yearTotal),
                  color: Math.abs(yearTotal) > 2 ? "#fff" : "#333",
                  textAlign: "center", fontSize: "12px", fontWeight: 700,
                }}>
                  {yearTotal > 0 ? "+" : ""}{yearTotal.toFixed(1)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
