/**
 * Reusable Lightweight Charts (TradingView) v5 wrapper for React.
 *
 * Supports: candlestick, line, area, volume histogram, MA overlays.
 * Built-in: mouse/touch zoom, pan, pinch zoom, auto Y-scale, crosshair.
 */

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  AreaSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type Time,
  createSeriesMarkers,
} from "lightweight-charts";

export type ChartMode = "candle" | "line" | "area";

export interface OHLCVPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartMarker {
  time: string;
  label: string;
  color: string;
}

interface Props {
  data: OHLCVPoint[];
  mode?: ChartMode;
  volume?: boolean;
  markers?: ChartMarker[];
  height?: number;
  showMA20?: boolean;
  showMA50?: boolean;
  showRSI?: boolean;
  showMACD?: boolean;
  upColor?: string;
  downColor?: string;
  lineColor?: string;
  onCrosshairMove?: (point: OHLCVPoint | null) => void;
  /** Called when visible range changes (zoom/pan). Returns visible bar count and logical range. */
  onVisibleRangeChange?: (visibleBars: number, fromIdx: number, toIdx: number) => void;
  /** Initial number of bars to show (from the end). If omitted, fitContent() shows all. */
  displayBars?: number;
  /** Explicit intraday flag — avoids misdetection from timestamp gaps (e.g. 5D over weekend) */
  intraday?: boolean;
}

function toTime(isoTime: string, intraday: boolean): Time {
  if (intraday) return Math.floor(new Date(isoTime).getTime() / 1000) as Time;
  return new Date(isoTime).toISOString().slice(0, 10) as Time;
}

function isIntraday(data: OHLCVPoint[]): boolean {
  if (data.length < 2) return false;
  return Math.abs(new Date(data[1].time).getTime() - new Date(data[0].time).getTime()) < 86400000;
}

function computeMA(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i + 1 < period) return null;
    const slice = closes.slice(i + 1 - period, i + 1);
    return slice.reduce((s, v) => s + v, 0) / period;
  });
}

function computeRSI(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = Array(closes.length).fill(null);
  if (closes.length < period + 1) return result;
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) avgGain += d; else avgLoss += Math.abs(d);
  }
  avgGain /= period; avgLoss /= period;
  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = ((avgGain * (period - 1)) + Math.max(d, 0)) / period;
    avgLoss = ((avgLoss * (period - 1)) + Math.max(-d, 0)) / period;
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return result;
}

function computeEMA(values: number[], period: number, mask?: (number | null)[]): (number | null)[] {
  const result: (number | null)[] = Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let prev: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (mask && mask[i] == null) continue;
    if (prev == null) { prev = values[i]; result[i] = prev; continue; }
    prev = (values[i] - prev) * k + prev;
    result[i] = prev;
  }
  return result;
}

function computeMACD(closes: number[]): { macd: (number | null)[]; signal: (number | null)[]; hist: (number | null)[] } {
  const ema12 = computeEMA(closes, 12);
  const ema26 = computeEMA(closes, 26);
  const macd = closes.map((_, i) => (ema12[i] != null && ema26[i] != null) ? ema12[i]! - ema26[i]! : null);
  const signal = computeEMA(macd.map(v => v ?? 0), 9, macd);
  const hist = macd.map((v, i) => (v != null && signal[i] != null) ? v - signal[i]! : null);
  return { macd, signal, hist };
}

export default function LightweightChart({
  data, mode = "candle", volume = true, markers, height = 400,
  showMA20 = false, showMA50 = false, showRSI = false, showMACD = false,
  upColor = "#16a34a", downColor = "#dc2626", lineColor = "#1a1a2e",
  onCrosshairMove, onVisibleRangeChange, displayBars, intraday: intradayProp,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  // Store callbacks in refs to avoid chart recreation when they change
  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange);
  onVisibleRangeChangeRef.current = onVisibleRangeChange;
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  onCrosshairMoveRef.current = onCrosshairMove;

  useEffect(() => {
    if (!containerRef.current || !data.length) return;

    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }

    // Fix #2: Use explicit intraday prop when available (avoids 5D weekend gap misdetection)
    const intraday = intradayProp ?? isIntraday(data);
    const tt = (t: string) => toTime(t, intraday);
    const valid = data.filter(d => d.close > 0);

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: fullscreen ? window.innerHeight - 40 : height,
      layout: { background: { type: ColorType.Solid, color: "#fff" }, textColor: "#333", fontSize: 11 },
      grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, autoScale: true },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false },
      handleScroll: { vertTouchDrag: false },
    });
    chartRef.current = chart;

    // Fix #1: Detect flat/synthetic intraday data (open=high=low=close) → force line mode
    // Candles with zero body are meaningless doji bars
    let effectiveMode = mode;
    if (mode === "candle" && intraday && valid.length >= 5) {
      const flatCount = valid.filter(d => d.open === d.close && d.high === d.close && d.low === d.close).length;
      if (flatCount / valid.length > 0.8) effectiveMode = "line";
    }

    // Main series
    if (effectiveMode === "candle") {
      const s = chart.addSeries(CandlestickSeries, {
        upColor, downColor, borderUpColor: upColor, borderDownColor: downColor,
        wickUpColor: upColor, wickDownColor: downColor,
      });
      s.setData(valid.filter(d => d.open > 0 && d.high > 0 && d.low > 0).map(d => ({
        time: tt(d.time), open: d.open, high: d.high, low: d.low, close: d.close,
      })));
      // Markers
      if (markers?.length) {
        createSeriesMarkers(s, markers.map(m => ({
          time: tt(m.time), position: "aboveBar" as const, color: m.color,
          shape: "circle" as const, text: m.label, size: 1,
        })).sort((a, b) => (a.time as number) - (b.time as number)));
      }
    } else if (effectiveMode === "area") {
      const s = chart.addSeries(AreaSeries, {
        lineColor, topColor: `${lineColor}33`, bottomColor: `${lineColor}05`, lineWidth: 2,
      });
      s.setData(valid.map(d => ({ time: tt(d.time), value: d.close })));
    } else {
      const s = chart.addSeries(LineSeries, { color: lineColor, lineWidth: 2 });
      s.setData(valid.map(d => ({ time: tt(d.time), value: d.close })));
    }

    // MA overlays
    if (showMA20 && valid.length >= 20) {
      const ma = chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 1, priceLineVisible: false });
      const vals = computeMA(valid.map(d => d.close), 20);
      ma.setData(valid.map((d, i) => vals[i] != null ? { time: tt(d.time), value: vals[i]! } : null).filter(Boolean) as any[]);
    }
    if (showMA50 && valid.length >= 50) {
      const ma = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false });
      const vals = computeMA(valid.map(d => d.close), 50);
      ma.setData(valid.map((d, i) => vals[i] != null ? { time: tt(d.time), value: vals[i]! } : null).filter(Boolean) as any[]);
    }

    // Volume
    if (volume) {
      const vs = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" }, priceScaleId: "vol",
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      // Fix #3: Volume color — compare with previous bar in the filtered array, not the original
      const volBars = valid.filter(d => d.volume > 0);
      vs.setData(volBars.map((d, i) => ({
        time: tt(d.time), value: d.volume,
        color: i === 0 || d.close >= volBars[i - 1].close ? "rgba(22,163,74,0.3)" : "rgba(220,38,38,0.25)",
      })));
    }

    // Crosshair
    chart.subscribeCrosshairMove((param) => {
      if (!onCrosshairMoveRef.current) return;
      if (!param.time) { onCrosshairMoveRef.current(null); return; }
      const idx = valid.findIndex(d => tt(d.time) === param.time);
      onCrosshairMoveRef.current(idx >= 0 ? valid[idx] : null);
    });

    // Show only the last `displayBars` bars if specified, otherwise fit all
    if (displayBars && displayBars < valid.length) {
      chart.timeScale().setVisibleLogicalRange({
        from: valid.length - displayBars,
        to: valid.length - 1,
      });
    } else {
      chart.timeScale().fitContent();
    }

    // Notify parent of visible range changes (zoom/pan)
    // Skip initial callbacks that fire during chart setup (fitContent / setVisibleLogicalRange)
    // Subscribe — skip initial setup callbacks (chart init fires 2-4 times)
    let initSkip = 4;
    const totalBars = valid.length;
    chart.timeScale().subscribeVisibleLogicalRangeChange((lr) => {
      if (initSkip > 0) { initSkip--; return; }
      if (!lr || !onVisibleRangeChangeRef.current) return;
      const bars = Math.round(lr.to - lr.from);
      const fromIdx = Math.max(0, Math.round(lr.from));
      const toIdx = Math.min(totalBars - 1, Math.round(lr.to));
      onVisibleRangeChangeRef.current(bars, fromIdx, toIdx);
    });

    // RSI pane (separate chart, synced time scale)
    if (rsiChartRef.current) { rsiChartRef.current.remove(); rsiChartRef.current = null; }
    if (showRSI && rsiContainerRef.current && valid.length >= 15) {
      const rsiChart = createChart(rsiContainerRef.current, {
        width: containerRef.current.clientWidth,
        height: 120,
        layout: { background: { type: ColorType.Solid, color: "#fff" }, textColor: "#888", fontSize: 10 },
        grid: { vertLines: { color: "#f5f5f5" }, horzLines: { color: "#f5f5f5" } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.05, bottom: 0.05 } },
        timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, visible: false },
        handleScroll: { vertTouchDrag: false },
      });
      rsiChartRef.current = rsiChart;

      const rsiValues = computeRSI(valid.map(d => d.close), 14);
      const rsiLine = rsiChart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 2, priceLineVisible: false });
      rsiLine.setData(valid.map((d, i) => rsiValues[i] != null ? { time: tt(d.time), value: rsiValues[i]! } : null).filter(Boolean) as any[]);

      // Overbought/oversold reference lines
      const ob = rsiChart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 1, lineStyle: 2, priceLineVisible: false, crosshairMarkerVisible: false });
      const os = rsiChart.addSeries(LineSeries, { color: "#10b981", lineWidth: 1, lineStyle: 2, priceLineVisible: false, crosshairMarkerVisible: false });
      const refData = [{ time: tt(valid[0].time), value: 0 }, { time: tt(valid[valid.length - 1].time), value: 0 }];
      ob.setData(refData.map(d => ({ ...d, value: 70 })));
      os.setData(refData.map(d => ({ ...d, value: 30 })));

      // Sync time scales
      chart.timeScale().subscribeVisibleLogicalRangeChange((lr) => { if (lr) rsiChart.timeScale().setVisibleLogicalRange(lr); });
      rsiChart.timeScale().subscribeVisibleLogicalRangeChange((lr) => { if (lr) chart.timeScale().setVisibleLogicalRange(lr); });
    }

    // MACD pane (separate chart, synced time scale)
    if (macdChartRef.current) { macdChartRef.current.remove(); macdChartRef.current = null; }
    if (showMACD && macdContainerRef.current && valid.length >= 27) {
      const macdChart = createChart(macdContainerRef.current, {
        width: containerRef.current.clientWidth,
        height: 140,
        layout: { background: { type: ColorType.Solid, color: "#fff" }, textColor: "#888", fontSize: 10 },
        grid: { vertLines: { color: "#f5f5f5" }, horzLines: { color: "#f5f5f5" } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.05, bottom: 0.05 } },
        timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, visible: false },
        handleScroll: { vertTouchDrag: false },
      });
      macdChartRef.current = macdChart;

      const closes = valid.map(d => d.close);
      const { macd: macdVals, signal: sigVals, hist: histVals } = computeMACD(closes);

      const histSeries = macdChart.addSeries(HistogramSeries, { priceLineVisible: false });
      histSeries.setData(valid.map((d, i) => histVals[i] != null ? { time: tt(d.time), value: histVals[i]!, color: histVals[i]! >= 0 ? "rgba(22,163,74,0.4)" : "rgba(220,38,38,0.35)" } : null).filter(Boolean) as any[]);

      const macdLine = macdChart.addSeries(LineSeries, { color: "#7c3aed", lineWidth: 2, priceLineVisible: false });
      macdLine.setData(valid.map((d, i) => macdVals[i] != null ? { time: tt(d.time), value: macdVals[i]! } : null).filter(Boolean) as any[]);

      const sigLine = macdChart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2, priceLineVisible: false });
      sigLine.setData(valid.map((d, i) => sigVals[i] != null ? { time: tt(d.time), value: sigVals[i]! } : null).filter(Boolean) as any[]);

      // Sync time scales
      chart.timeScale().subscribeVisibleLogicalRangeChange((lr) => { if (lr) macdChart.timeScale().setVisibleLogicalRange(lr); });
      macdChart.timeScale().subscribeVisibleLogicalRangeChange((lr) => { if (lr) chart.timeScale().setVisibleLogicalRange(lr); });
    }

    const ro = new ResizeObserver(() => {
      const w = containerRef.current?.clientWidth;
      if (w) {
        chart.applyOptions({ width: w });
        if (rsiChartRef.current) rsiChartRef.current.applyOptions({ width: w });
        if (macdChartRef.current) macdChartRef.current.applyOptions({ width: w });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove(); chartRef.current = null;
      if (rsiChartRef.current) { rsiChartRef.current.remove(); rsiChartRef.current = null; }
      if (macdChartRef.current) { macdChartRef.current.remove(); macdChartRef.current = null; }
    };
  }, [data, mode, volume, markers, height, showMA20, showMA50, showRSI, showMACD, upColor, downColor, lineColor, fullscreen, displayBars, intradayProp]);

  return (
    <div style={{ position: "relative" }}>
      <button className="btn btn-sm" style={{ position: "absolute", top: 4, right: 4, zIndex: 10, fontSize: 11 }}
        onClick={() => setFullscreen(v => !v)}>
        {fullscreen ? "✕" : "⛶"}
      </button>
      <div ref={containerRef} className={fullscreen ? "chart-fullscreen" : ""}
        style={{ width: "100%", height: fullscreen ? "100vh" : height }} />
      {showRSI && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#888", margin: "8px 0 2px" }}>RSI (14)</div>
          <div ref={rsiContainerRef} style={{ width: "100%", height: 120 }} />
        </div>
      )}
      {showMACD && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#888", margin: "8px 0 2px" }}>MACD (12, 26, 9)</div>
          <div ref={macdContainerRef} style={{ width: "100%", height: 140 }} />
        </div>
      )}
    </div>
  );
}
