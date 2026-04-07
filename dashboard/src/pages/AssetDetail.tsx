import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { LightweightChart } from "../components/charts";
import DirectionValue from "../components/DirectionValue";
import StockSearch from "../components/StockSearch";
// calcOHLCDomain no longer needed — LightweightChart auto-scales
import { orderStatusLabel } from "../lib/labels";
import { apiGet } from "../hooks/useApi";
import type { OrderHistoryItem, NewsItem } from "../types";

type RangeKey = "1m" | "10m" | "1H" | "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "3Y" | "5Y" | "10Y" | "MAX";
type ChartMode = "line" | "candles";

// NewsItem imported from types.ts

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
  data_quality?: "true_ohlc" | "snapshot";
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
  "1m": { interval: "1m", limit: 30, display: 30 },
  "10m": { interval: "1m", limit: 60, display: 60 },
  "1H": { interval: "1m", limit: 120, display: 120 },
  "1D": { interval: "1m", limit: 240, display: 240 },
  "5D": { interval: "1m", limit: 600, display: 600 },
  "1M": { interval: "1d", limit: 80, display: 30 },    // fetch 80, show 30 (MA50 needs 50 extra)
  "3M": { interval: "1d", limit: 140, display: 90 },
  "6M": { interval: "1d", limit: 230, display: 180 },
  "YTD": { interval: "1d", limit: 310, display: 260 },
  "1Y": { interval: "1d", limit: 310, display: 260 },
  "3Y": { interval: "1d", limit: 806, display: 756 },
  "5Y": { interval: "1d", limit: 1310, display: 1260 },
  "10Y": { interval: "1d", limit: 2570, display: 2520 },
  "MAX": { interval: "1d", limit: 5000, display: 5000 },
};

const PREFETCH_NEIGHBORS: Partial<Record<RangeKey, RangeKey[]>> = {
  "5D": ["1D", "1M"],
  "1M": ["5D", "3M"],
  "3M": ["1M", "6M"],
  "6M": ["3M", "1Y"],
  "1Y": ["6M"],
  "1D": ["1H", "5D"],
  "1H": ["10m", "1D"],
  "10m": ["1m", "1H"],
  "1m": ["10m"],
};

// All ranges now support candles (Lightweight Charts handles any data count)
const CANDLE_SUPPORTED_RANGES = new Set<RangeKey>(["1m", "10m", "1H", "1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "MAX"]);

export default function AssetDetailPage({ t, route }: { t: (k: string) => string; route: string }) {
  const stockCode = useMemo(() => route.split("/")[1] || "", [route]);
  const [range, setRange] = useState<RangeKey>("1M");
  const [chartMode, setChartMode] = useState<ChartMode>("line");
  const [showMa20, setShowMa20] = useState(true);
  const [showMa50, setShowMa50] = useState(true);
  const [showRsi, setShowRsi] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const [compareCode, setCompareCode] = useState("");
  const [overview, setOverview] = useState<AssetOverview | null>(null);
  const [compareOverview, setCompareOverview] = useState<AssetOverview | null>(null);
  const [chartData, setChartData] = useState<AssetChartPoint[]>([]);
  const [chartInterval, setChartInterval] = useState<string>("1d");
  const [dataQuality, setDataQuality] = useState<"true_ohlc" | "snapshot">("true_ohlc");
  const [compareChartData, setCompareChartData] = useState<AssetChartPoint[]>([]);
  const [periodReturns, setPeriodReturns] = useState<Array<{ key: RangeKey; value: number }>>([]);
  const [executionContext, setExecutionContext] = useState<AssetExecutionContext | null>(null);
  const [peerCandidates, setPeerCandidates] = useState<UniverseItem[]>([]);
  const [zoomStart, setZoomStart] = useState(0);
  const [zoomEnd, setZoomEnd] = useState(100);
  const [zoomLabel, setZoomLabel] = useState<RangeKey | null>(null);
  const [hoverPoint, setHoverPoint] = useState<any | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [isRangeSwitching, setIsRangeSwitching] = useState(false);
  const canUseCandles = CANDLE_SUPPORTED_RANGES.has(range) && dataQuality !== "snapshot";
  const autoRangeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const skipAutoRange = useRef(true);  // true on mount — wait for first data load to settle
  const lastAutoTarget = useRef<RangeKey | null>(null);
  const lastAutoDirection = useRef<"in" | "out" | null>(null);
  const wasAutoRange = useRef(false);
  const [anchorTime, setAnchorTime] = useState<string | undefined>(undefined);
  const [anchorBars, setAnchorBars] = useState<number | undefined>(undefined);
  const lastVisibleBarsRef = useRef(0);
  const chartCacheRef = useRef<Map<string, AssetChartResponse>>(new Map());
  const activeChartRequestRef = useRef(0);
  const prevStockCodeRef = useRef(stockCode);

  const applyChartResponse = useCallback((chartResponse: AssetChartResponse) => {
    setChartInterval(chartResponse.interval || "1d");
    setDataQuality(chartResponse.data_quality || "true_ohlc");
    const seen = new Map<string, AssetChartPoint>();
    for (const pt of chartResponse.points || []) seen.set(pt.time, pt);
    const deduped = [...seen.values()].sort((a, b) => a.time.localeCompare(b.time));
    setChartData(deduped);
  }, []);

  // Auto-switch range based on zoom level (debounced) + sync indicator panels
  const handleAutoRange = useCallback((visibleBars: number, fromIdx: number, toIdx: number) => {
    lastVisibleBarsRef.current = visibleBars;

    // Sync indicator panels with visible range
    const total = chartData.length;
    if (total > 0) {
      setZoomStart(Math.max(0, Math.round((fromIdx / total) * 100)));
      setZoomEnd(Math.min(100, Math.round((toIdx / total) * 100)));
    }

    // After a range change, skip auto-range until the chart settles
    if (skipAutoRange.current) return;

    let target: RangeKey | null = null;
    if (chartInterval === "1d") {
      if (range === "MAX") {
        if (visibleBars <= 2000) target = "10Y";
      } else if (range === "10Y") {
        if (visibleBars <= 1000) target = "5Y";
        else if (visibleBars >= 3000) target = "MAX";
      } else if (range === "5Y") {
        if (visibleBars <= 500) target = "3Y";
        else if (visibleBars >= 1500) target = "10Y";
      } else if (range === "3Y") {
        if (visibleBars <= 300) target = "1Y";
        else if (visibleBars >= 900) target = "5Y";
      } else if (range === "1Y") {
        if (visibleBars <= 170) target = "6M";
        else if (visibleBars >= 400) target = "3Y";
      } else if (range === "6M") {
        if (visibleBars <= 90) target = "3M";
        else if (visibleBars >= 230) target = "1Y";
      } else if (range === "3M") {
        if (visibleBars <= 28) target = "1M";
        else if (visibleBars >= 130) target = "6M";
      } else if (range === "1M") {
        if (visibleBars <= 6) target = "5D";
        else if (visibleBars >= 55) target = "3M";
      } else if (range === "5D") {
        if (visibleBars >= 12) target = "1M";
      } else {
        if (visibleBars <= 7) target = "5D";
        else if (visibleBars <= 35) target = "1M";
        else if (visibleBars <= 100) target = "3M";
        else if (visibleBars <= 200) target = "6M";
        else target = "1Y";
      }
    } else {
      if (range === "5D") {
        if (visibleBars <= 220) target = "1D";
        else if (visibleBars >= 520) target = "1M";
      } else if (range === "1D") {
        if (visibleBars <= 110) target = "1H";
        else if (visibleBars >= 340) target = "5D";
      } else if (range === "1H") {
        if (visibleBars <= 55) target = "10m";
        else if (visibleBars >= 170) target = "1D";
      } else if (range === "10m") {
        if (visibleBars <= 22) target = "1m";
        else if (visibleBars >= 95) target = "1H";
      } else if (range === "1m") {
        if (visibleBars >= 45) target = "10m";
      } else {
        if (visibleBars <= 30) target = "1m";
        else if (visibleBars <= 70) target = "10m";
        else if (visibleBars <= 130) target = "1H";
        else if (visibleBars <= 300) target = "1D";
        else target = "1M";
      }
    }

    if (target) setZoomLabel(target);

    // Determine zoom direction: is target a larger or smaller range than current?
    const rangeOrder: RangeKey[] = ["1m", "10m", "1H", "1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "MAX"];
    const curIdx = rangeOrder.indexOf(range);
    const tgtIdx = target ? rangeOrder.indexOf(target) : -1;
    const direction = tgtIdx > curIdx ? "out" : tgtIdx < curIdx ? "in" : null;

    // Clear oscillation guard when zoom direction reverses (user changed intent)
    if (direction && lastAutoDirection.current && direction !== lastAutoDirection.current) {
      lastAutoTarget.current = null;
    }

    // Auto-switch: skip if target equals current range or if we just came FROM this target (prevents A→B→A oscillation)
    if (target && target !== range && target !== lastAutoTarget.current) {
      if (autoRangeTimer.current) clearTimeout(autoRangeTimer.current);
      autoRangeTimer.current = setTimeout(() => {
        skipAutoRange.current = true;
        lastAutoTarget.current = range;
        lastAutoDirection.current = direction;
        wasAutoRange.current = true;
        // Save anchor: center of current visible range + bar count
        const midIdx = Math.round((fromIdx + toIdx) / 2);
        if (midIdx >= 0 && midIdx < chartData.length) {
          setAnchorTime(chartData[midIdx].time);
          setAnchorBars(lastVisibleBarsRef.current);
        }
        setRange(target);
      }, 600);
    }
  }, [chartInterval, range, chartData.length]);

  useEffect(() => {
    setZoomStart(0); setZoomEnd(100); setZoomLabel(null);
    skipAutoRange.current = true;  // block auto-range until new data settles
    if (autoRangeTimer.current) { clearTimeout(autoRangeTimer.current); autoRangeTimer.current = null; }
  }, [range, stockCode, chartInterval]);

  // Reset auto-range skip flag after chart data loads
  useEffect(() => {
    if (!initialLoading && !isRangeSwitching) {
      const timer = setTimeout(() => { skipAutoRange.current = false; }, 800);
      return () => clearTimeout(timer);
    }
  }, [initialLoading, isRangeSwitching, chartData]);

  // Clear oscillation guard when user manually clicks a range button
  const handleManualRange = useCallback((key: RangeKey) => {
    lastAutoTarget.current = null;
    lastAutoDirection.current = null;
    wasAutoRange.current = false;
    setAnchorTime(undefined);
    setAnchorBars(undefined);
    setRange(key);
  }, []);

  useEffect(() => {
    if (!stockCode) return;
    const stockChanged = prevStockCodeRef.current !== stockCode;
    prevStockCodeRef.current = stockCode;
    if (stockChanged) {
      chartCacheRef.current.clear();
      setOverview(null);
      setExecutionContext(null);
      setPeriodReturns([]);
    }
    let cancelled = false;
    const code = stockCode;
    Promise.all([
      apiGet<AssetOverview>(`/asset/${code}/overview`),
      apiGet<AssetReturnsResponse>(`/asset/${code}/period-returns`),
      apiGet<AssetExecutionContext>(`/asset/${code}/execution-context`),
    ])
      .then(([overviewData, returnsResponse, executionResponse]) => {
        if (cancelled) return;
        setOverview(overviewData);
        setPeriodReturns((Object.entries(returnsResponse.returns) as Array<[RangeKey, number]>).map(([key, value]) => ({ key, value })));
        setExecutionContext(executionResponse);
      })
      .catch((err) => { if (!cancelled) console.error(err); })
      .finally(() => { if (!cancelled) setInitialLoading(false); });
    return () => { cancelled = true; };
  }, [stockCode]);

  useEffect(() => {
    if (!stockCode) return;
    const cacheKey = `${stockCode}:${range}`;
    const cached = chartCacheRef.current.get(cacheKey);
    if (cached) {
      applyChartResponse(cached);
      setIsRangeSwitching(false);
      return;
    }

    const requestId = ++activeChartRequestRef.current;
    const hasExistingChart = chartData.length > 0;
    if (hasExistingChart) setIsRangeSwitching(true);

    apiGet<AssetChartResponse>(`/asset/${stockCode}/chart?range=${range}`)
      .then((chartResponse) => {
        if (requestId !== activeChartRequestRef.current) return;
        chartCacheRef.current.set(cacheKey, chartResponse);
        applyChartResponse(chartResponse);
      })
      .catch(console.error)
      .finally(() => {
        if (requestId === activeChartRequestRef.current) setIsRangeSwitching(false);
      });
  }, [applyChartResponse, range, stockCode]);

  useEffect(() => {
    if (!stockCode) return;
    const neighbors = PREFETCH_NEIGHBORS[range] || [];
    neighbors.forEach((neighbor) => {
      const cacheKey = `${stockCode}:${neighbor}`;
      if (chartCacheRef.current.has(cacheKey)) return;
      apiGet<AssetChartResponse>(`/asset/${stockCode}/chart?range=${neighbor}`)
        .then((response) => {
          chartCacheRef.current.set(cacheKey, response);
        })
        .catch(() => undefined);
    });
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
    if (!canUseCandles && chartMode === "candles") {
      setChartMode("line");
    }
  }, [canUseCandles, chartMode]);

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
      priceLine: bar.close,
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

  // Apply zoom to displayed points
  const zoomedPoints = useMemo(() => {
    if (zoomStart === 0 && zoomEnd === 100) return chartPoints;
    const startIdx = Math.floor((zoomStart / 100) * chartPoints.length);
    const endIdx = Math.max(startIdx + 2, Math.ceil((zoomEnd / 100) * chartPoints.length));
    return chartPoints.slice(startIdx, endIdx);
  }, [chartPoints, zoomStart, zoomEnd]);

  const latestOrder = executionContext?.latest_order || null;
  const activeRangeReturn = periodReturns.find((item) => item.key === range)?.value ?? 0;
  const isPositiveRange = activeRangeReturn >= 0;
  const priceStroke = isPositiveRange ? "#16a34a" : "#dc2626";
  const chartHigh = useMemo(() => (chartData.length ? Math.max(...chartData.map((item) => item.high)) : 0), [chartData]);
  const chartLow = useMemo(() => (chartData.length ? Math.min(...chartData.map((item) => item.low)) : 0), [chartData]);
  const averageVolume = useMemo(() => {
    if (!chartData.length) return 0;
    return Math.round(chartData.reduce((sum, item) => sum + item.volume, 0) / chartData.length);
  }, [chartData]);
  // Use overview only when it matches the current stock (prevents stale data display)
  const currentOverview = overview?.stock_code === stockCode ? overview : null;
  const relativeVolume = averageVolume > 0 && currentOverview ? currentOverview.volume / averageVolume : 0;
  const lwChartData = useMemo(() => chartData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume })), [chartData]);
  const activePoint = hoverPoint ?? zoomedPoints[zoomedPoints.length - 1] ?? null;
  // priceDomain no longer needed — LightweightChart auto-scales

  if (!stockCode) return <div className="card">{t("asset.noCode")}</div>;
  if (!currentOverview && chartData.length === 0) return <p className="text-secondary p-xl">{t("asset.loading")}</p>;

  return (
    <div className="page-content asset-detail-page">
      <section className="card asset-header">
        <div className="asset-header-main">
            <div className="asset-code-block">
            <div className="asset-name">{currentOverview?.stock_name || stockCode}</div>
            <div className="asset-meta">
              <span>{stockCode}</span>
              <span>{t("asset.market")}: {currentOverview?.market || "-"}</span>
              <span>{t("asset.sector")}: {currentOverview?.sector || "-"}</span>
            </div>
          </div>
          <div className="asset-price-block">
            <div className="asset-price">{currentOverview?.current_price?.toLocaleString() || "-"}</div>
            <DirectionValue value={currentOverview?.change_pct ?? 0} suffix="%" />
            <div className="text-secondary">
              {currentOverview ? <DirectionValue value={currentOverview.change} precision={0} /> : "-"}
            </div>
          </div>
        </div>
        <div className="asset-header-side">
          <div className="asset-session-badge">{t("asset.marketSession")}: {currentOverview?.session.description || "-"}</div>
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
              className={`asset-range-chip ${range === key ? "is-active" : ""} ${zoomLabel === key && range !== key ? "is-zoom-hint" : ""}`}
              onClick={() => handleManualRange(key)}
            >
              {t(`asset.range.${key}`)}
            </button>
          ))}
        </div>
        <div className="asset-chart-controls">
          <button className={`asset-toggle-chip ${chartMode === "line" ? "is-active" : ""}`} onClick={() => setChartMode("line")}>
            {t("asset.chartType.line")}
          </button>
          <button
            className={`asset-toggle-chip ${chartMode === "candles" ? "is-active" : ""}`}
            onClick={() => {
              if (canUseCandles) setChartMode("candles");
            }}
            disabled={!canUseCandles}
            title={canUseCandles ? undefined : "단기 구간에서는 캔들 차트를 지원하지 않습니다."}
          >
            {t("asset.chartType.candles")}
          </button>
          <button className={`asset-toggle-chip ${showMa20 ? "is-active" : ""}`} onClick={() => setShowMa20((value) => !value)}>
            {t("asset.overlay.ma20")}
          </button>
          <button className={`asset-toggle-chip ${showMa50 ? "is-active" : ""}`} onClick={() => setShowMa50((value) => !value)}>
            {t("asset.overlay.ma50")}
          </button>
          <button className={`asset-toggle-chip ${showRsi ? "is-active" : ""}`} onClick={() => setShowRsi((v) => !v)}>
            RSI
          </button>
          <button className={`asset-toggle-chip ${showMacd ? "is-active" : ""}`} onClick={() => setShowMacd((v) => !v)}>
            MACD
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
            {currentOverview?.stock_name || stockCode} ({stockCode})
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
              <h3 className="card-title">
                {currentOverview?.stock_name || stockCode} ({stockCode}) — {t("asset.chart")}
                <span className="live-dot" title="Live" />
              </h3>
              <div className="asset-chart-note">
                {compareCode && chartMode === "line" ? t("asset.compareModeNote")
                  : dataQuality === "snapshot" ? t("asset.intradayLineNote")
                  : t("asset.chartModeNote")}
                {isRangeSwitching ? <span className="text-secondary"> · syncing range...</span> : null}
              </div>
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
          {/* TradingView Lightweight Chart — zoom/pan/pinch built-in */}
          <LightweightChart
            data={lwChartData}
            mode={chartMode === "candles" && canUseCandles ? "candle" : "line"}
            volume
            showMA20={showMa20}
            showMA50={showMa50}
            showRSI={showRsi}
            showMACD={showMacd}
            height={460}
            displayBars={wasAutoRange.current ? undefined : RANGE_CONFIG[range].display}
            anchorTime={anchorTime}
            anchorBars={anchorBars}
            intraday={chartInterval === "1m"}
            upColor="#16a34a"
            downColor="#dc2626"
            lineColor={priceStroke}
            onCrosshairMove={(pt) => {
              if (pt) setHoverPoint({ ...pt, label: "", interval: chartInterval, ma20: null, ma50: null, primaryNormalized: 0, compareNormalized: null, rsi14: null, macd: null, macdSignal: null, macdHist: null, candleBase: 0, candleBody: 0, isUpBar: true, priceLine: pt.close });
              else setHoverPoint(null);
            }}
            onVisibleRangeChange={handleAutoRange}
          />
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
            <AssetStat label={t("asset.volume")} value={currentOverview?.volume?.toLocaleString() || "-"} />
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
  if (["1m", "10m", "1H", "1D", "5D"].includes(range) && interval === "1m") {
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
