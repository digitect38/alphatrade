/**
 * Reusable Lightweight Charts (TradingView) v5 wrapper for React.
 *
 * Single chart instance with optional overlays:
 * - Price: candlestick / line / area
 * - Volume histogram (bottom 15%)
 * - MA20 / MA50 overlays
 * - RSI(14) pane (bottom region, separate priceScale)
 * - MACD(12,26,9) pane (bottom region, separate priceScale)
 *
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
  onVisibleRangeChange?: (visibleBars: number, fromIdx: number, toIdx: number) => void;
  displayBars?: number;
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
  const chartRef = useRef<IChartApi | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange);
  onVisibleRangeChangeRef.current = onVisibleRangeChange;
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  onCrosshairMoveRef.current = onCrosshairMove;

  // Compute total height: main chart + indicator panes
  const rsiHeight = showRSI ? 80 : 0;
  const macdHeight = showMACD ? 90 : 0;
  const totalHeight = (fullscreen ? window.innerHeight - 40 : height) + rsiHeight + macdHeight;

  // Compute scaleMargins for the main price series to leave room at the bottom
  const paneCount = (showRSI ? 1 : 0) + (showMACD ? 1 : 0);
  const bottomReserved = paneCount > 0 ? (rsiHeight + macdHeight) / totalHeight : 0;
  const volTop = 1 - bottomReserved - 0.15; // volume sits just above indicator area

  useEffect(() => {
    if (!containerRef.current || !data.length) return;

    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }

    const intraday = intradayProp ?? isIntraday(data);
    const tt = (t: string) => toTime(t, intraday);
    const valid = data.filter(d => d.close > 0);

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: totalHeight,
      layout: { background: { type: ColorType.Solid, color: "#fff" }, textColor: "#333", fontSize: 11 },
      grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderVisible: false, autoScale: true,
        scaleMargins: { top: 0.02, bottom: bottomReserved + 0.02 },
      },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false },
      handleScroll: { vertTouchDrag: false },
    });
    chartRef.current = chart;

    // Detect flat/synthetic intraday data → force line mode
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
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: volTop, bottom: bottomReserved } });
      const volBars = valid.filter(d => d.volume > 0);
      vs.setData(volBars.map((d, i) => ({
        time: tt(d.time), value: d.volume,
        color: i === 0 || d.close >= volBars[i - 1].close ? "rgba(22,163,74,0.3)" : "rgba(220,38,38,0.25)",
      })));
    }

    // --- RSI pane (same chart, dedicated priceScale at bottom) ---
    if (showRSI && valid.length >= 15) {
      const rsiScaleId = "rsi";
      const rsiBottom = showMACD ? macdHeight / totalHeight : 0;
      const rsiTop = 1 - rsiBottom - rsiHeight / totalHeight;
      chart.priceScale(rsiScaleId).applyOptions({ scaleMargins: { top: rsiTop, bottom: rsiBottom }, borderVisible: false });

      const rsiValues = computeRSI(valid.map(d => d.close), 14);
      const rsiLine = chart.addSeries(LineSeries, {
        color: "#2563eb", lineWidth: 2, priceLineVisible: false, priceScaleId: rsiScaleId,
        lastValueVisible: true,
      });
      rsiLine.setData(valid.map((d, i) => rsiValues[i] != null ? { time: tt(d.time), value: rsiValues[i]! } : null).filter(Boolean) as any[]);

      // Overbought (70) / oversold (30) reference lines
      const ob = chart.addSeries(LineSeries, {
        color: "#ef4444", lineWidth: 1, lineStyle: 2, priceLineVisible: false,
        priceScaleId: rsiScaleId, crosshairMarkerVisible: false, lastValueVisible: false,
      });
      const os = chart.addSeries(LineSeries, {
        color: "#10b981", lineWidth: 1, lineStyle: 2, priceLineVisible: false,
        priceScaleId: rsiScaleId, crosshairMarkerVisible: false, lastValueVisible: false,
      });
      const refTimes = valid.filter((_, i) => rsiValues[i] != null);
      ob.setData(refTimes.map(d => ({ time: tt(d.time), value: 70 })));
      os.setData(refTimes.map(d => ({ time: tt(d.time), value: 30 })));
    }

    // --- MACD pane (same chart, dedicated priceScale at very bottom) ---
    if (showMACD && valid.length >= 27) {
      const macdScaleId = "macd";
      const macdTop = 1 - macdHeight / totalHeight;
      chart.priceScale(macdScaleId).applyOptions({ scaleMargins: { top: macdTop, bottom: 0 }, borderVisible: false });

      const closes = valid.map(d => d.close);
      const { macd: macdVals, signal: sigVals, hist: histVals } = computeMACD(closes);

      const histSeries = chart.addSeries(HistogramSeries, {
        priceLineVisible: false, priceScaleId: macdScaleId, lastValueVisible: false,
      });
      histSeries.setData(valid.map((d, i) => histVals[i] != null ? {
        time: tt(d.time), value: histVals[i]!,
        color: histVals[i]! >= 0 ? "rgba(22,163,74,0.4)" : "rgba(220,38,38,0.35)",
      } : null).filter(Boolean) as any[]);

      const macdLine = chart.addSeries(LineSeries, {
        color: "#7c3aed", lineWidth: 2, priceLineVisible: false,
        priceScaleId: macdScaleId, lastValueVisible: true,
      });
      macdLine.setData(valid.map((d, i) => macdVals[i] != null ? { time: tt(d.time), value: macdVals[i]! } : null).filter(Boolean) as any[]);

      const sigLine = chart.addSeries(LineSeries, {
        color: "#f59e0b", lineWidth: 2, priceLineVisible: false,
        priceScaleId: macdScaleId, lastValueVisible: false,
      });
      sigLine.setData(valid.map((d, i) => sigVals[i] != null ? { time: tt(d.time), value: sigVals[i]! } : null).filter(Boolean) as any[]);
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

    // Visible range change subscription — skip initial setup callbacks
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

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, [data, mode, volume, markers, totalHeight, showMA20, showMA50, showRSI, showMACD, upColor, downColor, lineColor, fullscreen, displayBars, intradayProp, bottomReserved, volTop, rsiHeight, macdHeight]);

  return (
    <div style={{ position: "relative" }}>
      <button className="btn btn-sm" style={{ position: "absolute", top: 4, right: 4, zIndex: 10, fontSize: 11 }}
        onClick={() => setFullscreen(v => !v)}>
        {fullscreen ? "✕" : "⛶"}
      </button>
      <div ref={containerRef} className={fullscreen ? "chart-fullscreen" : ""}
        style={{ width: "100%", height: totalHeight }} />
    </div>
  );
}
