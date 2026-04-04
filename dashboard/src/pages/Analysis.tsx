import { useEffect, useState } from "react";
import BenchmarkChart from "../components/BenchmarkChart";
import StockSearch from "../components/StockSearch";
import TechnicalChart from "../components/TechnicalChart";
import { apiGet, apiPost } from "../hooks/useApi";
import { parseOHLCVList } from "../lib/parse";
import type { OHLCVRecord, TechnicalResult } from "../types";

const signalColors: Record<string, string> = { bullish: "text-profit", bearish: "text-loss", neutral: "text-neutral" };
type AnalysisPresetKey = "1m" | "10m" | "1H" | "1D" | "1W" | "1M" | "3M" | "6M" | "1Y" | "3Y" | "5Y" | "10Y" | "ALL";

// Uses only intervals that exist in DB: "1m" (intraday ticks) and "1d" (daily bars)
// Intraday presets use 1m data; daily+ presets use 1d data
const ANALYSIS_PRESETS: Record<AnalysisPresetKey, { interval: string; period: number; limit: number }> = {
  "1m": { interval: "1m", period: 1, limit: 30 },       // Last 30 ticks (~30min)
  "10m": { interval: "1m", period: 1, limit: 60 },      // Last 60 ticks (~1hr)
  "1H": { interval: "1m", period: 1, limit: 120 },      // Last 120 ticks (~2hr)
  "1D": { interval: "1m", period: 1, limit: 200 },      // Today's all ticks
  "1W": { interval: "1d", period: 5, limit: 5 },        // 5 daily bars
  "1M": { interval: "1d", period: 22, limit: 22 },
  "3M": { interval: "1d", period: 66, limit: 66 },
  "6M": { interval: "1d", period: 132, limit: 132 },
  "1Y": { interval: "1d", period: 252, limit: 252 },
  "3Y": { interval: "1d", period: 756, limit: 756 },
  "5Y": { interval: "1d", period: 1260, limit: 1260 },
  "10Y": { interval: "1d", period: 2520, limit: 2520 },
  "ALL": { interval: "1d", period: 3000, limit: 3000 },
};

export default function AnalysisPage({ t: _t, initialCode }: { t: (k: string) => string; initialCode?: string }) {
  const [stockCode, setStockCode] = useState(initialCode || "005930");

  // Update when navigated with a new code
  useEffect(() => {
    if (initialCode && /^\d{6}$/.test(initialCode)) setStockCode(initialCode);
  }, [initialCode]);
  const [preset, setPreset] = useState<AnalysisPresetKey>("6M");
  const [technical, setTechnical] = useState<TechnicalResult | null>(null);
  const [ohlcv, setOhlcv] = useState<OHLCVRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const isIntraday = (p: AnalysisPresetKey) => ["1m", "10m", "1H", "1D"].includes(p);

  const analyze = async (nextStockCode: string, nextPreset: AnalysisPresetKey) => {
    const selected = ANALYSIS_PRESETS[nextPreset];
    setLoading(true);
    try {
      // Fetch OHLCV data
      const data = await apiGet<Record<string, unknown>[]>(
        `/data/ohlcv/latest?stock_code=${nextStockCode}&interval=${selected.interval}&limit=${selected.limit}`,
      ).then(parseOHLCVList);

      // Technical analysis only for daily intervals with enough data
      // (intraday ticks don't have enough bars for SMA20/60)
      let tech: TechnicalResult | null = null;
      if (!isIntraday(nextPreset)) {
        try {
          tech = await apiPost<TechnicalResult>("/analyze/technical", {
            stock_code: nextStockCode,
            interval: selected.interval,
            period: selected.period,
          });
        } catch { /* skip technical for short periods */ }
      }

      setTechnical(tech);
      setOhlcv([...data].reverse());
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (!/^\d{6}$/.test(stockCode)) return;
    void analyze(stockCode, preset);
  }, [stockCode, preset]);

  return (
    <div className="page-content">
      <div className="card analysis-toolbar">
        <div className="analysis-toolbar-row">
          <StockSearch
            value={stockCode}
            onChange={(code) => setStockCode(code)}
            placeholder={_t("common.placeholder.stockCode")}
            t={_t}
          />
          {loading ? <span className="analysis-loading-state">{_t("analysis.analyzing")}</span> : null}
          {technical && (
            <span className="font-bold" style={{ fontSize: "14px" }}>
              {_t("analysis.currentPrice")}: {technical.current_price?.toLocaleString()}{_t("common.won")}
            </span>
          )}
          {!technical && ohlcv.length > 0 && (
            <span className="font-bold" style={{ fontSize: "14px" }}>
              {_t("analysis.currentPrice")}: {ohlcv[ohlcv.length - 1]?.close?.toLocaleString()}{_t("common.won")}
            </span>
          )}
          {isIntraday(preset) && (
            <span className="text-secondary" style={{ fontSize: "12px", marginLeft: 8 }}>
              ({_t("analysis.intradayNote")})
            </span>
          )}
        </div>
        <div className="analysis-toolbar-row analysis-toolbar-row-period">
          <span className="analysis-period-label">{_t("analysis.period")}</span>
          <div className="asset-range-group" aria-label={_t("analysis.period")}>
            {(Object.keys(ANALYSIS_PRESETS) as AnalysisPresetKey[]).map((option) => (
              <button
                key={option}
                type="button"
                className={`asset-range-chip ${preset === option ? "is-active" : ""}`}
                onClick={() => setPreset(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      </div>

      {ohlcv.length > 0 && (
        <TechnicalChart
          data={ohlcv}
          sma20={technical?.indicators.sma_20}
          sma60={technical?.indicators.sma_60}
          periodLabel={preset}
          interval={ANALYSIS_PRESETS[preset].interval}
          t={_t}
        />
      )}

      {/* Benchmark comparison */}
      {ohlcv.length > 0 && (
        <BenchmarkChart stockCode={stockCode} period={ANALYSIS_PRESETS[preset].limit} t={_t} />
      )}

      {technical && (
        <>
          <div className="card">
            <h3 className="card-title">{_t("analysis.scores")}</h3>
            <div className="flex gap-xl" style={{ fontSize: "14px" }}>
              <div>
                <span className="text-secondary">{_t("analysis.trend")}: </span>
                <strong className={technical.trend_score >= 0 ? "text-profit" : "text-loss"}>
                  {technical.trend_score.toFixed(3)}
                </strong>
              </div>
              <div>
                <span className="text-secondary">{_t("analysis.momentum")}: </span>
                <strong className={technical.momentum_score >= 0 ? "text-profit" : "text-loss"}>
                  {technical.momentum_score.toFixed(3)}
                </strong>
              </div>
              <div>
                <span className="text-secondary">{_t("analysis.overall")}: </span>
                <strong className={technical.overall_score >= 0 ? "text-profit" : "text-loss"}>
                  {technical.overall_score.toFixed(3)}
                </strong>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">{_t("analysis.signals")} ({technical.signals.length})</h3>
            <div className="flex flex-wrap gap-sm">
              {technical.signals.map((s, i) => (
                <div key={i} style={{ padding: "6px 12px", borderRadius: "6px", background: "#f5f5f5", fontSize: "12px" }}>
                  <strong className={signalColors[s.signal]}>{s.indicator}</strong>
                  {" "}{s.description}
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">{_t("analysis.keyIndicators")}</h3>
            <div className="metrics-grid metrics-grid-4" style={{ fontSize: "13px" }}>
              {Object.entries(technical.indicators)
                .filter(([_, v]) => v !== null)
                .map(([k, v]) => (
                  <div key={k} style={{ padding: "6px" }}>
                    <div className="metric-label">{k}</div>
                    <div className="font-bold">{typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v}</div>
                  </div>
                ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
