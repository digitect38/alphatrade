import { useState } from "react";
import StockSearch from "../components/StockSearch";
import TechnicalChart from "../components/TechnicalChart";
import { apiGet, apiPost } from "../hooks/useApi";
import type { OHLCVRecord, TechnicalResult } from "../types";

const card = { background: "#fff", borderRadius: "8px", padding: "20px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" } as const;

const signalColors: Record<string, string> = { bullish: "#16a34a", bearish: "#dc2626", neutral: "#888" };

export default function AnalysisPage({ t: _t }: { t: (k: string) => string }) {
  const [stockCode, setStockCode] = useState("005930");
  const [technical, setTechnical] = useState<TechnicalResult | null>(null);
  const [ohlcv, setOhlcv] = useState<OHLCVRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const analyze = async () => {
    setLoading(true);
    try {
      const [tech, data] = await Promise.all([
        apiPost<TechnicalResult>("/analyze/technical", { stock_code: stockCode }),
        apiGet<OHLCVRecord[]>(`/data/ohlcv/latest?stock_code=${stockCode}&interval=1d&limit=60`),
      ]);
      setTechnical(tech);
      setOhlcv(data);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ ...card, display: "flex", gap: "12px", alignItems: "center" }}>
        <StockSearch
          value={stockCode}
          onChange={(code) => setStockCode(code)}
          placeholder={_t("common.placeholder.stockCode")}
        />
        <button
          onClick={analyze}
          disabled={loading}
          style={{ padding: "8px 20px", background: "#1a1a2e", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "14px" }}
        >
          {loading ? _t("analysis.analyzing") : _t("analysis.analyze")}
        </button>
        {technical && (
          <span style={{ fontSize: "14px", fontWeight: 600 }}>
            {_t("analysis.currentPrice")}: {technical.current_price?.toLocaleString()}{_t("common.won")}
          </span>
        )}
      </div>

      {ohlcv.length > 0 && (
        <TechnicalChart
          data={ohlcv}
          sma20={technical?.indicators.sma_20}
          sma60={technical?.indicators.sma_60}
        />
      )}

      {technical && (
        <>
          <div style={card}>
            <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("analysis.scores")}</h3>
            <div style={{ display: "flex", gap: "32px", fontSize: "14px" }}>
              <div>
                <span style={{ color: "#888" }}>{_t("analysis.trend")}: </span>
                <strong style={{ color: technical.trend_score >= 0 ? "#16a34a" : "#dc2626" }}>
                  {technical.trend_score.toFixed(3)}
                </strong>
              </div>
              <div>
                <span style={{ color: "#888" }}>{_t("analysis.momentum")}: </span>
                <strong style={{ color: technical.momentum_score >= 0 ? "#16a34a" : "#dc2626" }}>
                  {technical.momentum_score.toFixed(3)}
                </strong>
              </div>
              <div>
                <span style={{ color: "#888" }}>{_t("analysis.overall")}: </span>
                <strong style={{ color: technical.overall_score >= 0 ? "#16a34a" : "#dc2626" }}>
                  {technical.overall_score.toFixed(3)}
                </strong>
              </div>
            </div>
          </div>

          <div style={card}>
            <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("analysis.signals")} ({technical.signals.length})</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {technical.signals.map((s, i) => (
                <div key={i} style={{ padding: "6px 12px", borderRadius: "6px", background: "#f5f5f5", fontSize: "12px" }}>
                  <strong style={{ color: signalColors[s.signal] }}>{s.indicator}</strong>
                  {" "}{s.description}
                </div>
              ))}
            </div>
          </div>

          <div style={card}>
            <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("analysis.keyIndicators")}</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", fontSize: "13px" }}>
              {Object.entries(technical.indicators)
                .filter(([_, v]) => v !== null)
                .map(([k, v]) => (
                  <div key={k} style={{ padding: "6px" }}>
                    <div style={{ color: "#888", fontSize: "11px" }}>{k}</div>
                    <div style={{ fontWeight: 600 }}>{typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v}</div>
                  </div>
                ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
