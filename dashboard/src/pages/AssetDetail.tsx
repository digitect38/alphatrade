import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Customized,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import DirectionValue from "../components/DirectionValue";
import StockSearch from "../components/StockSearch";
import { orderStatusLabel } from "../lib/labels";
import { apiGet } from "../hooks/useApi";
import type { OrderHistoryItem } from "../types";

type RangeKey = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y";
type ChartMode = "line" | "candles";

interface NewsItem {
  time: string;
  source: string;
  title: string;
  content: string;
  url: string;
}

interface AssetOverview {
  stock_code: string;
  stock_name: string;
  market: string;
  sector: string;
  current_price: number;
  change: number;
  change_pct: number;
  volume: number;
  updated_at: string | null;
  session: { current_session: string; description: string; kst_time: string };
}

interface AssetChartPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface AssetChartResponse {
  stock_code: string;
  range: RangeKey;
  interval: string;
  points: AssetChartPoint[];
}

interface AssetReturnsResponse {
  stock_code: string;
  returns: Record<string, number>;
}

interface AssetSignalSummary {
  overall_signal: string;
  confidence: number;
  trend_score: number;
  momentum_score: number;
  overall_score: number;
  top_signals: Array<{
    indicator: string;
    signal: string;
    strength: number;
    description: string;
  }>;
}

interface AssetExecutionContext {
  stock_code: string;
  session: { current_session: string; description: string; kst_time: string };
  latest_order: OrderHistoryItem | null;
  recent_orders: OrderHistoryItem[];
  recent_news: NewsItem[];
  signal_summary: AssetSignalSummary;
}

interface UniverseItem {
  stock_code: string;
  stock_name: string;
  market: string;
  sector: string;
}

// display = bars to show, fetch = bars to request (extra for MA50 pre-computation)
const RANGE_CONFIG: Record<RangeKey, { interval: string; limit: number; display: number }> = {
  "1D": { interval: "1m", limit: 240, display: 240 },
  "5D": { interval: "1m", limit: 600, display: 600 },
  "1M": { interval: "1d", limit: 80, display: 30 },    // fetch 80, show 30 (MA50 needs 50 extra)
  "3M": { interval: "1d", limit: 140, display: 90 },
  "6M": { interval: "1d", limit: 230, display: 180 },
  "YTD": { interval: "1d", limit: 310, display: 260 },
  "1Y": { interval: "1d", limit: 310, display: 260 },
};

export default function AssetDetailPage({ t, route }: { t: (k: string) => string; route: string }) {
  const stockCode = useMemo(() => route.split("/")[1] || "", [route]);
  const [range, setRange] = useState<RangeKey>("1M");
  const [chartMode, setChartMode] = useState<ChartMode>("line");
  const [showMa20, setShowMa20] = useState(true);
  const [showMa50, setShowMa50] = useState(true);
  const [compareCode, setCompareCode] = useState("");
  const [overview, setOverview] = useState<AssetOverview | null>(null);
  const [compareOverview, setCompareOverview] = useState<AssetOverview | null>(null);
  const [chartData, setChartData] = useState<AssetChartPoint[]>([]);
  const [chartInterval, setChartInterval] = useState<string>("1d");
  const [compareChartData, setCompareChartData] = useState<AssetChartPoint[]>([]);
  const [periodReturns, setPeriodReturns] = useState<Array<{ key: RangeKey; value: number }>>([]);
  const [executionContext, setExecutionContext] = useState<AssetExecutionContext | null>(null);
  const [peerCandidates, setPeerCandidates] = useState<UniverseItem[]>([]);
  const [hoverPoint, setHoverPoint] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!stockCode) return;
    setLoading(true);
    Promise.all([
      apiGet<AssetOverview>(`/asset/${stockCode}/overview`),
      apiGet<AssetChartResponse>(`/asset/${stockCode}/chart?range=${range}`),
      apiGet<AssetReturnsResponse>(`/asset/${stockCode}/period-returns`),
      apiGet<AssetExecutionContext>(`/asset/${stockCode}/execution-context`),
    ])
      .then(([overviewData, chartResponse, returnsResponse, executionResponse]) => {
        setOverview(overviewData);
        setChartInterval(chartResponse.interval || "1d");
        // Deduplicate by time (keep last entry for each timestamp)
        const rawPoints = chartResponse.points || [];
        const seen = new Map<string, AssetChartPoint>();
        for (const pt of rawPoints) seen.set(pt.time, pt);
        setChartData([...seen.values()]);
        setPeriodReturns((Object.entries(returnsResponse.returns) as Array<[RangeKey, number]>).map(([key, value]) => ({ key, value })));
        setExecutionContext(executionResponse);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [range, stockCode]);

  useEffect(() => {
    if (!compareCode) {
      setCompareOverview(null);
      setCompareChartData([]);
      return;
    }

    Promise.all([
      apiGet<AssetOverview>(`/asset/${compareCode}/overview`),
      apiGet<AssetChartResponse>(`/asset/${compareCode}/chart?range=${range}`),
    ])
      .then(([overviewData, chartResponse]) => {
        setCompareOverview(overviewData);
        setCompareChartData(chartResponse.points || []);
      })
      .catch(() => {
        setCompareOverview(null);
        setCompareChartData([]);
      });
  }, [compareCode, range]);

  useEffect(() => {
    if (!overview?.sector) return;
    apiGet<UniverseItem[]>("/scanner/universe")
      .then((items) => {
        const peers = items
          .filter((item) => item.stock_code !== stockCode && item.sector === overview.sector)
          .slice(0, 4);
        setPeerCandidates(peers);
      })
      .catch(() => setPeerCandidates([]));
  }, [overview?.sector, stockCode]);

  const chartPoints = useMemo(() => {
    // Compute indicators on full data (includes pre-fetch buffer for MA)
    const ma20Values = computeMovingAverage(chartData, 20);
    const ma50Values = computeMovingAverage(chartData, 50);
    const primaryNormalized = normalizeSeries(chartData);
    const compareNormalized = normalizeSeries(compareChartData);
    const compareByTime = new Map(compareChartData.map((bar, index) => [bar.time, compareNormalized[index]]));
    const rsi14 = computeRsi(chartData, 14);
    const macd = computeMacd(chartData);

    const allPoints = chartData.map((bar, index) => ({
      label: formatChartLabel(bar.time, range, chartInterval),
      interval: chartInterval,
      time: bar.time,
      close: bar.close,
      volume: bar.volume,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      ma20: ma20Values[index],
      ma50: ma50Values[index],
      primaryNormalized: primaryNormalized[index],
      compareNormalized: compareByTime.get(bar.time) ?? null,
      rsi14: rsi14[index],
      macd: macd.macd[index],
      macdSignal: macd.signal[index],
      macdHist: macd.histogram[index],
      // Candle bar rendering: stacked bars (invisible base + colored body)
      candleBase: Math.min(bar.open, bar.close),  // invisible spacer
      candleBody: Math.abs(bar.close - bar.open) || 1,  // visible colored body (min 1 for doji)
      isUpBar: index === 0 ? true : bar.close >= chartData[index - 1].close,
    }));

    // Trim to display range (extra data was for MA pre-computation)
    const displayCount = RANGE_CONFIG[range].display;
    return allPoints.length > displayCount ? allPoints.slice(allPoints.length - displayCount) : allPoints;
  }, [chartData, compareChartData, chartInterval, range]);

  const latestOrder = executionContext?.latest_order || null;
  const activeRangeReturn = periodReturns.find((item) => item.key === range)?.value ?? 0;
  const isPositiveRange = activeRangeReturn >= 0;
  const chartHigh = useMemo(() => (chartData.length ? Math.max(...chartData.map((item) => item.high)) : 0), [chartData]);
  const chartLow = useMemo(() => (chartData.length ? Math.min(...chartData.map((item) => item.low)) : 0), [chartData]);
  const averageVolume = useMemo(() => {
    if (!chartData.length) return 0;
    return Math.round(chartData.reduce((sum, item) => sum + item.volume, 0) / chartData.length);
  }, [chartData]);
  const relativeVolume = averageVolume > 0 && overview ? overview.volume / averageVolume : 0;
  const activePoint = hoverPoint ?? chartPoints[chartPoints.length - 1] ?? null;
  const priceDomain = useMemo((): [number, number] => {
    if (!chartPoints.length) return [0, 100];
    const prices = chartPoints.flatMap((d) => [d.open, d.high, d.low, d.close]).filter(Number.isFinite);
    if (!prices.length) return [0, 100];
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const pad = Math.max((max - min) * 0.08, max * 0.01, 100);
    return [Math.max(0, min - pad), max + pad];
  }, [chartPoints]);

  if (!stockCode) return <div className="card">{t("asset.noCode")}</div>;
  if (loading) return <p className="text-secondary p-xl">{t("asset.loading")}</p>;

  return (
    <div className="page-content asset-detail-page">
      <section className="card asset-header">
        <div className="asset-header-main">
            <div className="asset-code-block">
            <div className="asset-name">{overview?.stock_name || stockCode}</div>
            <div className="asset-meta">
              <span>{stockCode}</span>
              <span>{t("asset.market")}: {overview?.market || "-"}</span>
              <span>{t("asset.sector")}: {overview?.sector || "-"}</span>
            </div>
          </div>
          <div className="asset-price-block">
            <div className="asset-price">{overview?.current_price?.toLocaleString() || "-"}</div>
            <DirectionValue value={overview?.change_pct ?? 0} suffix="%" />
            <div className="text-secondary">
              {overview ? <DirectionValue value={overview.change} precision={0} /> : "-"}
            </div>
          </div>
        </div>
        <div className="asset-header-side">
          <div className="asset-session-badge">{t("asset.marketSession")}: {overview?.session.description || "-"}</div>
          <div className="asset-header-actions">
            <button className="btn btn-sm" onClick={() => { window.location.hash = "command"; }}>{t("asset.backCommand")}</button>
            <button className="btn btn-sm" onClick={() => { window.location.hash = "trend"; }}>{t("asset.backIntel")}</button>
          </div>
        </div>
      </section>

      <section className="asset-hero-strip">
        <div className="card asset-hero-card">
          <div className="asset-hero-label">{t("asset.rangeReturn")}</div>
          <DirectionValue value={activeRangeReturn} suffix="%" />
        </div>
        <div className="card asset-hero-card">
          <div className="asset-hero-label">{t("asset.dayRange")}</div>
          <div className="asset-hero-value">{chartLow ? `${chartLow.toLocaleString()} - ${chartHigh.toLocaleString()}` : "-"}</div>
        </div>
        <div className="card asset-hero-card">
          <div className="asset-hero-label">{t("asset.avgVolume")}</div>
          <div className="asset-hero-value">{averageVolume ? averageVolume.toLocaleString() : "-"}</div>
        </div>
        <div className="card asset-hero-card">
          <div className="asset-hero-label">{t("asset.relativeVolume")}</div>
          <div className="asset-hero-value">{relativeVolume ? `${relativeVolume.toFixed(2)}x` : "-"}</div>
        </div>
      </section>
      <div className="asset-swipe-hint">{t("asset.swipeHint")}</div>

      <section className="card asset-range-strip">
        <div className="asset-range-group">
          {(Object.keys(RANGE_CONFIG) as RangeKey[]).map((key) => (
            <button
              key={key}
              className={`asset-range-chip ${range === key ? "is-active" : ""}`}
              onClick={() => setRange(key)}
            >
              {t(`asset.range.${key}`)}
            </button>
          ))}
        </div>
        <div className="asset-chart-controls">
          <button className={`asset-toggle-chip ${chartMode === "line" ? "is-active" : ""}`} onClick={() => setChartMode("line")}>
            {t("asset.chartType.line")}
          </button>
          <button className={`asset-toggle-chip ${chartMode === "candles" ? "is-active" : ""}`} onClick={() => setChartMode("candles")}>
            {t("asset.chartType.candles")}
          </button>
          <button className={`asset-toggle-chip ${showMa20 ? "is-active" : ""}`} onClick={() => setShowMa20((value) => !value)}>
            {t("asset.overlay.ma20")}
          </button>
          <button className={`asset-toggle-chip ${showMa50 ? "is-active" : ""}`} onClick={() => setShowMa50((value) => !value)}>
            {t("asset.overlay.ma50")}
          </button>
        </div>
      </section>

      <section className="card asset-compare-strip">
        <div className="asset-compare-form">
          <div className="asset-compare-label">{t("asset.compare")}</div>
          <StockSearch
            value={compareCode}
            onChange={(code) => {
              if (!code || code === stockCode) return;
              setCompareCode(code);
              setChartMode("line");
            }}
            placeholder={t("asset.comparePlaceholder")}
            t={t}
          />
          {compareCode ? (
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => {
                setCompareCode("");
              }}
            >
              {t("asset.compareClear")}
            </button>
          ) : null}
        </div>
        <div className="asset-compare-summary">
          <span className="asset-compare-pill asset-compare-pill-primary">
            {overview?.stock_name || stockCode} ({stockCode})
          </span>
          {compareOverview ? (
            <span className="asset-compare-pill asset-compare-pill-compare">
              {compareOverview.stock_name} ({compareOverview.stock_code})
            </span>
          ) : (
            <span className="text-secondary">{t("asset.compareHint")}</span>
          )}
        </div>
      </section>

      {peerCandidates.length > 0 ? (
        <section className="card asset-peer-strip">
          <div className="asset-compare-label">{t("asset.quickCompare")}</div>
          <div className="asset-peer-buttons">
            {peerCandidates.map((peer) => (
              <button
                key={peer.stock_code}
                className={`asset-toggle-chip ${compareCode === peer.stock_code ? "is-active" : ""}`}
                onClick={() => {
                  setCompareCode(peer.stock_code);
                  setChartMode("line");
                }}
              >
                {peer.stock_name}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <div className="asset-swipe-hint">{t("asset.swipePanelsHint")}</div>
      <section className="asset-main-grid">
        <div className="card asset-chart-card">
          <div className="asset-section-header">
            <div>
              <h3 className="card-title">{t("asset.chart")}</h3>
              <div className="asset-chart-note">{compareCode && chartMode === "line" ? t("asset.compareModeNote") : t("asset.chartModeNote")}</div>
            </div>
            <div className="asset-live-header">
              <div className="asset-live-price">
                {(chartMode === "line" && compareCode ? activePoint?.primaryNormalized : activePoint?.close)?.toLocaleString?.() ?? "-"}
                {chartMode === "line" && compareCode ? "%" : ""}
              </div>
              <div className="asset-live-grid">
                <span>{t("asset.open")}</span><strong>{activePoint?.open?.toLocaleString?.() ?? "-"}</strong>
                <span>{t("asset.high")}</span><strong>{activePoint?.high?.toLocaleString?.() ?? "-"}</strong>
                <span>{t("asset.low")}</span><strong>{activePoint?.low?.toLocaleString?.() ?? "-"}</strong>
                <span>{t("asset.close")}</span><strong>{activePoint?.close?.toLocaleString?.() ?? "-"}</strong>
                <span>{t("asset.volume")}</span><strong>{activePoint?.volume?.toLocaleString?.() ?? "-"}</strong>
                {compareCode && chartMode === "line" ? (
                  <>
                    <span>{t("asset.compareTarget")}</span><strong>{activePoint?.compareNormalized != null ? `${activePoint.compareNormalized.toFixed(2)}%` : "-"}</strong>
                  </>
                ) : null}
              </div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={460}>
            <ComposedChart
              data={chartPoints}
              syncId="asset-detail"
              onMouseMove={(state) => {
                const payload = state?.activePayload?.[0]?.payload;
                if (payload) setHoverPoint(payload);
              }}
              onMouseLeave={() => setHoverPoint(null)}
            >
              <defs>
                <linearGradient id="assetChartFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={isPositiveRange ? "var(--color-profit)" : "var(--color-loss)"} stopOpacity={0.24} />
                  <stop offset="100%" stopColor={isPositiveRange ? "var(--color-profit)" : "var(--color-loss)"} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
              <XAxis dataKey="label" fontSize={11} minTickGap={24} />
              <YAxis
                yAxisId="price"
                fontSize={11}
                domain={chartMode === "line" && compareCode ? ["auto", "auto"] : priceDomain}
                tickFormatter={(value: number) => (chartMode === "line" && compareCode ? `${value.toFixed(1)}%` : value >= 1000 ? `${(value / 1000).toFixed(0)}k` : `${value}`)}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0]?.payload;
                  if (!point) return null;

                  return (
                    <div className="asset-chart-tooltip">
                      <div className="asset-chart-tooltip-time">{label ? new Date(point.time).toLocaleString("ko-KR") : ""}</div>
                      <div className="asset-chart-tooltip-grid">
                        <span>{t("asset.open")}</span><strong>{point.open.toLocaleString()}</strong>
                        <span>{t("asset.high")}</span><strong>{point.high.toLocaleString()}</strong>
                        <span>{t("asset.low")}</span><strong>{point.low.toLocaleString()}</strong>
                        <span>{t("asset.close")}</span><strong>{point.close.toLocaleString()}</strong>
                        <span>{t("asset.volume")}</span><strong>{point.volume.toLocaleString()}</strong>
                        {compareCode && chartMode === "line" ? (
                          <>
                            <span>{t("asset.compareBase")}</span><strong>{`${point.primaryNormalized?.toFixed(2) ?? "0.00"}%`}</strong>
                            <span>{t("asset.compareTarget")}</span><strong>{point.compareNormalized != null ? `${point.compareNormalized.toFixed(2)}%` : "-"}</strong>
                          </>
                        ) : null}
                      </div>
                    </div>
                  );
                }}
                labelFormatter={(_label, payload) => payload?.[0]?.payload?.time ? new Date(payload[0].payload.time).toLocaleString("ko-KR") : ""}
              />
              {overview?.current_price ? <ReferenceLine yAxisId="price" y={overview.current_price - overview.change} stroke="#94a3b8" strokeDasharray="4 4" /> : null}
              {chartMode === "candles" ? (
                <Customized component={(cProps: any) => {
                  // Get Y axis scale from Recharts internals
                  const yMap = cProps.yAxisMap;
                  const yAxis = yMap ? (yMap["price"] || Object.values(yMap)[0]) : null;
                  const xMap = cProps.xAxisMap;
                  const xAxis = xMap ? Object.values(xMap)[0] : null;
                  if (!yAxis?.scale || !xAxis) return <g />;

                  const yScale = yAxis.scale;
                  const xLeft = (xAxis as any).x || 65;
                  const xWidth = (xAxis as any).width || 650;
                  const n = chartPoints.length;
                  const candleW = Math.max(1.5, Math.min(10, (xWidth / n) * 0.7));

                  return (
                    <g>
                      {chartPoints.map((pt, i) => {
                        const cx = xLeft + (i + 0.5) * (xWidth / n);
                        const oY = yScale(pt.open);
                        const cY = yScale(pt.close);
                        const hY = yScale(pt.high);
                        const lY = yScale(pt.low);
                        if ([oY, cY, hY, lY].some((v) => !Number.isFinite(v))) return null;
                        const rising = pt.close >= pt.open;
                        return (
                          <g key={i}>
                            <line x1={cx} x2={cx} y1={hY} y2={lY}
                              stroke={rising ? "var(--color-profit)" : "var(--color-loss)"} strokeWidth={1} />
                            <rect x={cx - candleW / 2} y={Math.min(oY, cY)}
                              width={candleW} height={Math.max(1, Math.abs(cY - oY))} rx={0.5}
                              fill={rising ? "rgba(22,163,74,0.5)" : "rgba(220,38,38,0.5)"}
                              stroke={rising ? "var(--color-profit)" : "var(--color-loss)"} strokeWidth={0.7} />
                          </g>
                        );
                      })}
                    </g>
                  );
                }} />
              ) : (
                <>
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey={compareCode ? "primaryNormalized" : "close"}
                    stroke={isPositiveRange ? "var(--color-profit)" : "var(--color-loss)"}
                    strokeWidth={2.5}
                    dot={false}
                    connectNulls
                    name={overview?.stock_name || stockCode}
                  />
                  {compareCode ? (
                    <Line
                      yAxisId="price"
                      type="monotone"
                      dataKey="compareNormalized"
                      stroke="#7c3aed"
                      strokeWidth={2.2}
                      dot={false}
                      connectNulls
                      name={compareOverview?.stock_name || compareCode}
                    />
                  ) : null}
                </>
              )}
              {showMa20 ? <Line yAxisId="price" type="monotone" dataKey="ma20" stroke="#2563eb" strokeWidth={1.75} dot={false} connectNulls name={t("asset.overlay.ma20")} /> : null}
              {showMa50 ? <Line yAxisId="price" type="monotone" dataKey="ma50" stroke="#f59e0b" strokeWidth={1.75} dot={false} connectNulls name={t("asset.overlay.ma50")} /> : null}
            </ComposedChart>
          </ResponsiveContainer>
          <div className="asset-volume-panel">
            <div className="asset-volume-label">{t("asset.volume")}</div>
            <ResponsiveContainer width="100%" height={110}>
              <ComposedChart data={chartPoints} syncId="asset-detail">
                <XAxis dataKey="label" hide />
                <YAxis hide />
                <Tooltip
                  formatter={(value: number) => [value.toLocaleString(), t("asset.volume")]}
                  labelFormatter={(_label, payload) => payload?.[0]?.payload?.time ? new Date(payload[0].payload.time).toLocaleString("ko-KR") : ""}
                />
                <Bar dataKey="volume" radius={[3, 3, 0, 0]}>
                  {chartPoints.map((point) => (
                    <Cell
                      key={point.time}
                      fill={point.isUpBar ? "rgba(16, 185, 129, 0.35)" : "rgba(239, 68, 68, 0.28)"}
                    />
                  ))}
                </Bar>
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="asset-indicator-stack">
            <div className="asset-indicator-panel">
              <div className="asset-volume-label">{t("asset.indicator.rsi")}</div>
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={chartPoints} syncId="asset-detail">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
                  <XAxis dataKey="label" hide />
                  <YAxis domain={[0, 100]} hide />
                  <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 4" />
                  <ReferenceLine y={30} stroke="#10b981" strokeDasharray="4 4" />
                  <Tooltip formatter={(value: number) => [Number(value).toFixed(2), t("asset.indicator.rsi")]} />
                  <Line type="monotone" dataKey="rsi14" stroke="#2563eb" strokeWidth={2} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="asset-indicator-panel">
              <div className="asset-volume-label">{t("asset.indicator.macd")}</div>
              <ResponsiveContainer width="100%" height={140}>
                <ComposedChart data={chartPoints} syncId="asset-detail">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light)" />
                  <XAxis dataKey="label" hide />
                  <YAxis hide />
                  <Tooltip formatter={(value: number) => [Number(value).toFixed(2), "MACD"]} />
                  <Bar dataKey="macdHist" fill="rgba(14, 165, 233, 0.24)" />
                  <Line type="monotone" dataKey="macd" stroke="#7c3aed" strokeWidth={2} dot={false} connectNulls />
                  <Line type="monotone" dataKey="macdSignal" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="card asset-side-card">
          <div className="asset-section-header">
            <h3 className="card-title">{t("asset.keyStats")}</h3>
          </div>
          <div className="asset-stats-list">
            <AssetStat label={t("asset.currentSignal")} value={executionContext?.signal_summary.overall_signal?.toUpperCase() || "-"} />
            <AssetStat label={t("asset.signalStrength")} value={executionContext ? `${(executionContext.signal_summary.confidence * 100).toFixed(0)}%` : "-"} />
            <AssetStat label={t("asset.trendScore")} value={executionContext?.signal_summary.trend_score?.toFixed(3) || "-"} />
            <AssetStat label={t("asset.momentumScore")} value={executionContext?.signal_summary.momentum_score?.toFixed(3) || "-"} />
            <AssetStat label={t("asset.volume")} value={overview?.volume?.toLocaleString() || "-"} />
            <AssetStat label={t("asset.latestOrder")} value={latestOrder ? orderStatusLabel(latestOrder.status, t) : "-"} />
          </div>
        </div>
      </section>

      <section className="card">
        <div className="asset-section-header">
          <h3 className="card-title">{t("asset.periodReturns")}</h3>
        </div>
        <div className="asset-return-strip">
          {periodReturns.map((item) => (
            <div key={item.key} className="asset-return-card">
              <div className="asset-return-label">{t(`asset.range.${item.key}`)}</div>
              <DirectionValue value={item.value} suffix="%" />
            </div>
          ))}
        </div>
      </section>

      <div className="asset-swipe-hint">{t("asset.swipePanelsHint")}</div>
      <section className="asset-bottom-grid">
        <div className="card">
          <div className="asset-section-header">
            <h3 className="card-title">{t("asset.latestNews")}</h3>
          </div>
          <div className="asset-news-list">
            {executionContext?.recent_news.length === 0 && <div className="text-secondary">{t("asset.noNews")}</div>}
            {executionContext?.recent_news.map((item, index) => (
              <a key={`${item.time}-${index}`} href={item.url} target="_blank" rel="noreferrer" className="asset-news-item">
                <div className="asset-news-title">{item.title}</div>
                <div className="asset-news-meta">{item.source} · {new Date(item.time).toLocaleString("ko-KR")}</div>
              </a>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="asset-section-header">
            <h3 className="card-title">{t("asset.executionContext")}</h3>
          </div>
          <div className="asset-orders-list">
            {executionContext?.recent_orders.length === 0 && <div className="text-secondary">{t("asset.noOrders")}</div>}
            {executionContext?.recent_orders.map((order) => (
              <div key={order.order_id} className="asset-order-item">
                <div className="asset-order-top">
                  <span>{orderStatusLabel(order.status, t)}</span>
                  <span className="text-secondary">{new Date(order.time).toLocaleString("ko-KR")}</span>
                </div>
                <div className="asset-order-main">
                  <span>{t(order.side === "BUY" ? "signal.buy" : "signal.sell")} {order.quantity}</span>
                  <span>{order.filled_qty}/{order.quantity}</span>
                </div>
              </div>
            ))}
            {executionContext?.signal_summary.top_signals.slice(0, 3).map((signal, index) => (
              <div key={`${signal.indicator}-${index}`} className="asset-order-item">
                <div className="asset-order-top">
                  <span>{signal.indicator}</span>
                  <span className="text-secondary">{signal.signal}</span>
                </div>
                <div className="asset-order-main">
                  <span>{signal.description}</span>
                  <span>{(signal.strength * 100).toFixed(0)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function AssetStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="asset-stat-row">
      <span className="text-secondary">{label}</span>
      <span className="font-heavy">{value}</span>
    </div>
  );
}

function formatChartLabel(value: string, range: RangeKey, interval = "1d") {
  const date = new Date(value);
  if ((range === "1D" || range === "5D") && interval === "1m") {
    return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

function computeMovingAverage(data: AssetChartPoint[], period: number) {
  return data.map((_, index) => {
    if (index + 1 < period) return null;
    const slice = data.slice(index + 1 - period, index + 1);
    const total = slice.reduce((sum, item) => sum + item.close, 0);
    return Number((total / period).toFixed(2));
  });
}

function normalizeSeries(data: AssetChartPoint[]) {
  const base = data[0]?.close ?? 0;
  if (!base) return data.map(() => null);
  return data.map((item) => Number((((item.close / base) - 1) * 100).toFixed(2)));
}

function computeRsi(data: AssetChartPoint[], period: number) {
  if (data.length < period + 1) return data.map(() => null);

  const closes = data.map((item) => item.close);
  const result = Array<number | null>(data.length).fill(null);
  let avgGain = 0;
  let avgLoss = 0;

  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1];
    if (delta >= 0) avgGain += delta;
    else avgLoss += Math.abs(delta);
  }

  avgGain /= period;
  avgLoss /= period;
  result[period] = avgLoss === 0 ? 100 : Number((100 - (100 / (1 + avgGain / avgLoss))).toFixed(2));

  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    const gain = Math.max(delta, 0);
    const loss = Math.max(-delta, 0);
    avgGain = ((avgGain * (period - 1)) + gain) / period;
    avgLoss = ((avgLoss * (period - 1)) + loss) / period;
    result[i] = avgLoss === 0 ? 100 : Number((100 - (100 / (1 + avgGain / avgLoss))).toFixed(2));
  }

  return result;
}

function computeMacd(data: AssetChartPoint[]) {
  const closes = data.map((item) => item.close);
  const ema12 = computeEma(closes, 12);
  const ema26 = computeEma(closes, 26);
  const macd = closes.map((_, index) => {
    if (ema12[index] == null || ema26[index] == null) return null;
    return Number((ema12[index]! - ema26[index]!).toFixed(2));
  });
  const signal = computeEma(macd.map((value) => value ?? 0), 9, macd);
  const histogram = macd.map((value, index) => {
    if (value == null || signal[index] == null) return null;
    return Number((value - signal[index]!).toFixed(2));
  });
  return { macd, signal, histogram };
}

function computeEma(values: number[], period: number, mask?: Array<number | null>) {
  const result = Array<number | null>(values.length).fill(null);
  const multiplier = 2 / (period + 1);
  let previous: number | null = null;

  for (let i = 0; i < values.length; i++) {
    if (mask && mask[i] == null) {
      result[i] = null;
      continue;
    }
    if (previous == null) {
      previous = values[i];
      result[i] = Number(previous.toFixed(2));
      continue;
    }
    previous = ((values[i] - previous) * multiplier) + previous;
    result[i] = Number(previous.toFixed(2));
  }

  return result;
}

// CandlestickLayer removed — candles now rendered via Bar shape prop
