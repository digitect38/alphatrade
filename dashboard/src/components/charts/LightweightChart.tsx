/**
 * LightweightChart — Multi-pane TradingView Lightweight Charts v5 component.
 *
 * Pane 1: Price (candle/line/area) + Volume + MA20/MA50 overlays + Markers
 * Pane 2 (optional): RSI(14) with overbought/oversold reference lines
 * Pane 3 (optional): MACD(12,26,9) — histogram + MACD line + signal line
 *
 * All panes share a single chart instance: synced time scale, crosshair, zoom/pan.
 * Pane dividers are draggable (built-in Lightweight Charts feature).
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

// ─── Time helpers ────────────────────────────────────────────────

function toTime(iso: string, intraday: boolean): Time {
  if (intraday) return Math.floor(new Date(iso).getTime() / 1000) as Time;
  return new Date(iso).toISOString().slice(0, 10) as Time;
}

function isIntradayData(data: OHLCVPoint[]): boolean {
  if (data.length < 2) return false;
  return Math.abs(new Date(data[1].time).getTime() - new Date(data[0].time).getTime()) < 86400000;
}

// ─── Indicator computations ──────────────────────────────────────

function computeMA(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i + 1 < period) return null;
    return closes.slice(i + 1 - period, i + 1).reduce((s, v) => s + v, 0) / period;
  });
}

function computeRSI(closes: number[], period = 14): (number | null)[] {
  const r: (number | null)[] = Array(closes.length).fill(null);
  if (closes.length < period + 1) return r;
  let ag = 0, al = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) ag += d; else al -= d;
  }
  ag /= period; al /= period;
  r[period] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    ag = (ag * (period - 1) + Math.max(d, 0)) / period;
    al = (al * (period - 1) + Math.max(-d, 0)) / period;
    r[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  }
  return r;
}

function computeEMA(vals: number[], p: number, mask?: (number | null)[]): (number | null)[] {
  const r: (number | null)[] = Array(vals.length).fill(null);
  const k = 2 / (p + 1);
  let prev: number | null = null;
  for (let i = 0; i < vals.length; i++) {
    if (mask && mask[i] == null) continue;
    if (prev == null) { prev = vals[i]; r[i] = prev; continue; }
    prev = (vals[i] - prev) * k + prev;
    r[i] = prev;
  }
  return r;
}

function computeMACD(closes: number[]) {
  const e12 = computeEMA(closes, 12);
  const e26 = computeEMA(closes, 26);
  const macd = closes.map((_, i) => (e12[i] != null && e26[i] != null) ? e12[i]! - e26[i]! : null);
  const signal = computeEMA(macd.map(v => v ?? 0), 9, macd);
  const hist = macd.map((v, i) => (v != null && signal[i] != null) ? v - signal[i]! : null);
  return { macd, signal, hist };
}

// ─── Component ───────────────────────────────────────────────────

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

  // Dynamic height: in fullscreen all panes fit within viewport; in normal mode they extend below
  const totalHeight = fullscreen
    ? window.innerHeight - 40
    : height + (showRSI ? 160 : 0) + (showMACD ? 180 : 0);

  useEffect(() => {
    if (!containerRef.current || !data.length) return;
    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }

    const intraday = intradayProp ?? isIntradayData(data);
    const tt = (t: string) => toTime(t, intraday);
    // Filter valid bars, normalize OHLC, deduplicate by time, sort ascending
    const seen = new Map<string, OHLCVPoint>();
    for (const d of data) {
      if (d.close <= 0) continue;
      const key = intraday ? String(Math.floor(new Date(d.time).getTime() / 1000)) : new Date(d.time).toISOString().slice(0, 10);
      seen.set(key, {
        ...d,
        open: d.open > 0 ? d.open : d.close,
        high: d.high > 0 ? d.high : d.close,
        low: d.low > 0 ? d.low : d.close,
      });
    }
    const valid = [...seen.values()].sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
    if (!valid.length) return;

    // Detect flat/synthetic intraday data → force line mode
    let effectiveMode: ChartMode = mode;
    if (mode === "candle" && intraday && valid.length >= 5) {
      const flatCount = valid.filter(d => d.open === d.close && d.high === d.close && d.low === d.close).length;
      if (flatCount / valid.length > 0.8) effectiveMode = "line";
    }

    // ── Create chart ──
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: totalHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#fff" },
        textColor: "#333", fontSize: 11,
        panes: { separatorColor: "#e0e0e0", separatorHoverColor: "#bdbdbd" },
      },
      grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, autoScale: true },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, minBarSpacing: 0.5 },
      handleScroll: { vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
    });
    chartRef.current = chart;

    // Prevent page scroll when wheeling on chart (enables zoom-out)
    const el = containerRef.current;
    const preventScroll = (e: WheelEvent) => { e.preventDefault(); };
    el.addEventListener("wheel", preventScroll, { passive: false });

    // ── Create panes ──
    const pricePane = chart.panes()[0];
    let rsiPaneIdx: number | undefined;
    let macdPaneIdx: number | undefined;

    if (showRSI) {
      rsiPaneIdx = chart.addPane().paneIndex();
    }
    if (showMACD) {
      macdPaneIdx = chart.addPane().paneIndex();
    }

    // Set pane proportions
    pricePane.setStretchFactor(600);
    if (rsiPaneIdx != null) chart.panes()[rsiPaneIdx].setStretchFactor(200);
    if (macdPaneIdx != null) chart.panes()[macdPaneIdx].setStretchFactor(200);

    // ══════════════════════════════════════════════════════════════
    // PANE 0 — Price + Volume + MA + Markers
    // ══════════════════════════════════════════════════════════════

    if (effectiveMode === "candle") {
      const s = chart.addSeries(CandlestickSeries, {
        upColor, downColor, borderUpColor: upColor, borderDownColor: downColor,
        wickUpColor: upColor, wickDownColor: downColor,
      });
      s.setData(valid.map(d => ({
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
    const closes = valid.map(d => d.close);
    if (showMA20 && valid.length >= 20) {
      const ma = chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 1, priceLineVisible: false });
      const vals = computeMA(closes, 20);
      ma.setData(valid.map((d, i) => vals[i] != null ? { time: tt(d.time), value: vals[i]! } : null).filter(Boolean) as any[]);
    }
    if (showMA50 && valid.length >= 50) {
      const ma = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false });
      const vals = computeMA(closes, 50);
      ma.setData(valid.map((d, i) => vals[i] != null ? { time: tt(d.time), value: vals[i]! } : null).filter(Boolean) as any[]);
    }

    // Volume
    if (volume) {
      const vs = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" }, priceScaleId: "vol",
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      const vb = valid.filter(d => d.volume > 0);
      vs.setData(vb.map((d, i) => ({
        time: tt(d.time), value: d.volume,
        color: i === 0 || d.close >= vb[i - 1].close ? "rgba(22,163,74,0.25)" : "rgba(220,38,38,0.2)",
      })));
    }

    // ══════════════════════════════════════════════════════════════
    // PANE 1 — RSI(14)
    // ══════════════════════════════════════════════════════════════

    if (showRSI && rsiPaneIdx != null && valid.length >= 15) {
      const rsiVals = computeRSI(closes, 14);
      const rsiLine = chart.addSeries(LineSeries, {
        color: "#7c3aed", lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
      }, rsiPaneIdx);
      rsiLine.setData(valid.map((d, i) => rsiVals[i] != null ? { time: tt(d.time), value: rsiVals[i]! } : null).filter(Boolean) as any[]);

      const refTimes = valid.filter((_, i) => rsiVals[i] != null);
      const ob = chart.addSeries(LineSeries, {
        color: "#ef4444", lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, crosshairMarkerVisible: false, lastValueVisible: false,
      }, rsiPaneIdx);
      ob.setData(refTimes.map(d => ({ time: tt(d.time), value: 70 })));
      const os = chart.addSeries(LineSeries, {
        color: "#10b981", lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, crosshairMarkerVisible: false, lastValueVisible: false,
      }, rsiPaneIdx);
      os.setData(refTimes.map(d => ({ time: tt(d.time), value: 30 })));
    }

    // ══════════════════════════════════════════════════════════════
    // PANE 2 — MACD(12, 26, 9)
    // ══════════════════════════════════════════════════════════════

    if (showMACD && macdPaneIdx != null && valid.length >= 27) {
      const { macd, signal, hist } = computeMACD(closes);

      const histS = chart.addSeries(HistogramSeries, {
        priceLineVisible: false, lastValueVisible: false,
      }, macdPaneIdx);
      histS.setData(valid.map((d, i) => hist[i] != null ? {
        time: tt(d.time), value: hist[i]!,
        color: hist[i]! >= 0 ? "rgba(22,163,74,0.45)" : "rgba(220,38,38,0.4)",
      } : null).filter(Boolean) as any[]);

      const macdLine = chart.addSeries(LineSeries, {
        color: "#7c3aed", lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
      }, macdPaneIdx);
      macdLine.setData(valid.map((d, i) => macd[i] != null ? { time: tt(d.time), value: macd[i]! } : null).filter(Boolean) as any[]);

      const sigLine = chart.addSeries(LineSeries, {
        color: "#f59e0b", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      }, macdPaneIdx);
      sigLine.setData(valid.map((d, i) => signal[i] != null ? { time: tt(d.time), value: signal[i]! } : null).filter(Boolean) as any[]);
    }

    // ── Crosshair ──
    chart.subscribeCrosshairMove((param) => {
      if (!onCrosshairMoveRef.current) return;
      if (!param.time) { onCrosshairMoveRef.current(null); return; }
      const idx = valid.findIndex(d => tt(d.time) === param.time);
      onCrosshairMoveRef.current(idx >= 0 ? valid[idx] : null);
    });

    // ── Initial visible range ──
    if (displayBars && displayBars < valid.length) {
      chart.timeScale().setVisibleLogicalRange({
        from: valid.length - displayBars,
        to: valid.length - 1,
      });
    } else {
      chart.timeScale().fitContent();
    }

    // ── Visible range change subscription (skip initial setup callbacks) ──
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

    // ── Resize observer ──
    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => { ro.disconnect(); el.removeEventListener("wheel", preventScroll); chart.remove(); chartRef.current = null; };
  }, [data, mode, volume, markers, totalHeight, showMA20, showMA50, showRSI, showMACD, upColor, downColor, lineColor, fullscreen, displayBars, intradayProp]);

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
