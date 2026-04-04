/**
 * @deprecated Use LightweightChart with volume={true} instead.
 * This component is kept for backward compatibility but is no longer used
 * since LightweightChart includes built-in volume rendering.
 */
import { Bar, Cell, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface VolumePoint {
  label: string;
  time: string;
  volume: number;
  isUpBar: boolean;
}

export default function VolumePanel({
  data, height = 110, syncId, t,
}: {
  data: VolumePoint[];
  height?: number;
  syncId?: string;
  t: (k: string) => string;
}) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-secondary)" }}>
        {t("asset.volume")}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} syncId={syncId}>
          <XAxis dataKey="label" hide />
          <YAxis hide />
          <Tooltip
            formatter={(value: number) => [value.toLocaleString(), t("asset.volume")]}
            labelFormatter={(_l, payload) =>
              payload?.[0]?.payload?.time ? new Date(payload[0].payload.time).toLocaleString("ko-KR") : ""
            }
          />
          <Bar dataKey="volume" radius={[3, 3, 0, 0]}>
            {data.map((pt, i) => (
              <Cell key={i} fill={pt.isUpBar ? "rgba(16, 185, 129, 0.35)" : "rgba(239, 68, 68, 0.28)"} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
