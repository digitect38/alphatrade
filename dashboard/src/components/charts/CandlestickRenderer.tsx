/**
 * Reusable candlestick renderer for Recharts ComposedChart.
 *
 * Uses index-based x positioning (not xScale) for reliability with any data count.
 * Must be used inside <Customized component={...} />.
 */

interface CandlePoint {
  open: number;
  high: number;
  low: number;
  close: number;
  time: string;
}

interface CandlestickProps {
  data: CandlePoint[];
  yAxisMap?: Record<string, any>;
  xAxisMap?: Record<string, any>;
  yAxisId?: string;
}

export function renderCandlesticks({ data, yAxisMap, xAxisMap, yAxisId = "price" }: CandlestickProps) {
  const yAxis = yAxisMap ? (yAxisMap[yAxisId] || Object.values(yAxisMap)[0]) : null;
  const xAxis = xAxisMap ? Object.values(xAxisMap)[0] : null;
  if (!yAxis?.scale || !xAxis || !data.length) return <g />;

  const yScale = yAxis.scale;
  const xLeft = (xAxis as any).x || 65;
  const xWidth = (xAxis as any).width || 650;
  const n = data.length;
  const candleW = Math.max(1.5, Math.min(10, (xWidth / n) * 0.7));

  return (
    <g>
      {data.map((pt, i) => {
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
}
