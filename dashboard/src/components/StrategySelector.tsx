import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";

interface Preset {
  key: string;
  name: string;
  name_en: string;
  description: string;
  weights: Record<string, number>;
  buy_threshold: number;
  sell_threshold: number;
  risk_level: string;
}

interface ActiveConfig {
  preset: string;
  weights: Record<string, number>;
  buy_threshold: number;
  sell_threshold: number;
}

const RISK_COLORS: Record<string, string> = {
  low: "text-profit",
  medium: "text-warning",
  high: "text-loss",
  very_high: "text-loss",
  custom: "text-secondary",
};

const RISK_LABELS: Record<string, string> = {
  low: "안전",
  medium: "보통",
  high: "공격",
  very_high: "매우 공격",
  custom: "사용자",
};

export default function StrategySelector({ t: _t }: { t: (k: string) => string }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [active, setActive] = useState<ActiveConfig | null>(null);
  const [customWeights, setCustomWeights] = useState<Record<string, number>>({});
  const [customBuy, setCustomBuy] = useState(0.15);
  const [customSell, setCustomSell] = useState(-0.15);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiGet<{ presets: Preset[] }>("/strategy/presets").then((d) => setPresets(d.presets)).catch(() => {});
    apiGet<ActiveConfig>("/strategy/active").then((d) => {
      setActive(d);
      setCustomWeights(d.weights || {});
      setCustomBuy(d.buy_threshold || 0.15);
      setCustomSell(d.sell_threshold || -0.15);
    }).catch(() => {});
  }, []);

  const selectPreset = async (key: string) => {
    setSaving(true);
    const body = key === "custom"
      ? { preset: "custom", weights: customWeights, buy_threshold: customBuy, sell_threshold: customSell }
      : { preset: key };
    try {
      const resp = await apiPost<{ active: ActiveConfig }>("/strategy/active", body);
      setActive(resp.active);
      if (resp.active.weights) setCustomWeights(resp.active.weights);
      if (resp.active.buy_threshold != null) setCustomBuy(resp.active.buy_threshold);
      if (resp.active.sell_threshold != null) setCustomSell(resp.active.sell_threshold);
    } catch { /* ignore */ }
    setSaving(false);
  };

  const updateWeight = (key: string, val: number) => {
    setCustomWeights((prev) => ({ ...prev, [key]: val }));
  };

  const isCustom = active?.preset === "custom";
  const weightSum = Object.values(customWeights).reduce((s, v) => s + v, 0);

  return (
    <div className="card">
      <h3 className="card-title">전략 선택</h3>

      {/* Preset grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "8px", marginBottom: "16px" }}>
        {presets.filter((p) => p.key !== "custom").map((p) => (
          <button
            key={p.key}
            onClick={() => selectPreset(p.key)}
            disabled={saving}
            className="card"
            style={{
              border: active?.preset === p.key ? "2px solid var(--color-accent)" : "1px solid var(--color-border-light)",
              background: active?.preset === p.key ? "#f0f4ff" : "#fff",
              cursor: "pointer", textAlign: "left", padding: "12px",
            }}
          >
            <div className="font-bold" style={{ fontSize: "13px", marginBottom: "4px" }}>{p.name}</div>
            <div className="text-secondary" style={{ fontSize: "11px", lineHeight: 1.4 }}>{p.description}</div>
            <div style={{ marginTop: "6px" }}>
              <span className={`font-heavy ${RISK_COLORS[p.risk_level]}`} style={{ fontSize: "11px" }}>
                {RISK_LABELS[p.risk_level] || p.risk_level}
              </span>
            </div>
          </button>
        ))}
      </div>

      {/* Custom weights editor */}
      <details open={isCustom}>
        <summary className="font-bold" style={{ cursor: "pointer", fontSize: "13px", marginBottom: "8px" }}>
          사용자 정의 가중치 {isCustom && "✏️"}
        </summary>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "12px" }}>
          {["momentum", "mean_reversion", "volume", "sentiment"].map((key) => (
            <div key={key} className="flex items-center gap-sm">
              <label style={{ fontSize: "12px", width: "90px" }}>{key}</label>
              <input
                type="range" min={0} max={100} step={5}
                value={Math.round((customWeights[key] || 0) * 100)}
                onChange={(e) => updateWeight(key, Number(e.target.value) / 100)}
                style={{ flex: 1, accentColor: "var(--color-accent)" }}
              />
              <span style={{ fontSize: "12px", width: "35px", textAlign: "right" }}>
                {Math.round((customWeights[key] || 0) * 100)}%
              </span>
            </div>
          ))}
        </div>
        <div className="flex gap-md items-center" style={{ fontSize: "12px", marginBottom: "8px" }}>
          <span className={weightSum > 1.01 || weightSum < 0.99 ? "text-loss" : "text-profit"}>
            합계: {Math.round(weightSum * 100)}%
          </span>
          <span>매수 임계: </span>
          <input type="number" step={0.05} value={customBuy} onChange={(e) => setCustomBuy(Number(e.target.value))}
            className="input" style={{ width: "70px", fontSize: "12px" }} />
          <span>매도 임계: </span>
          <input type="number" step={0.05} value={customSell} onChange={(e) => setCustomSell(Number(e.target.value))}
            className="input" style={{ width: "70px", fontSize: "12px" }} />
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => selectPreset("custom")} disabled={saving}>
          {saving ? "저장 중..." : "사용자 정의 적용"}
        </button>
      </details>

      {/* Active config summary */}
      {active && (
        <div className="flex gap-lg items-center" style={{ marginTop: "12px", fontSize: "12px", padding: "8px", background: "#f8fafc", borderRadius: "6px" }}>
          <span className="font-heavy">활성: {presets.find((p) => p.key === active.preset)?.name || active.preset}</span>
          <span className="text-secondary">
            M:{Math.round((active.weights?.momentum || 0) * 100)}%
            R:{Math.round((active.weights?.mean_reversion || 0) * 100)}%
            V:{Math.round((active.weights?.volume || 0) * 100)}%
            S:{Math.round((active.weights?.sentiment || 0) * 100)}%
          </span>
          <span className="text-secondary">BUY&gt;{active.buy_threshold} SELL&lt;{active.sell_threshold}</span>
        </div>
      )}
    </div>
  );
}
