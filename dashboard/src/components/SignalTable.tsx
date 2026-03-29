import type { StrategySignal } from "../types";

export default function SignalTable({ signals, t }: { signals: StrategySignal[]; t: (k: string) => string }) {
  return (
    <div className="card">
      <h3 className="card-title">{t("dash.strategySignals")}</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("th.code")}</th>
            <th>{t("th.signal")}</th>
            <th className="text-right">{t("th.score")}</th>
            <th className="text-right">{t("th.strength")}</th>
            <th>{t("th.topReason")}</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.stock_code}>
              <td className="font-bold">{s.stock_code}</td>
              <td className={`font-heavy ${s.signal === "BUY" ? "text-buy" : s.signal === "SELL" ? "text-sell" : "text-neutral"}`}>
                {s.signal}
              </td>
              <td className="text-right">{s.ensemble_score.toFixed(3)}</td>
              <td className="text-right">{(s.strength * 100).toFixed(0)}%</td>
              <td className="text-secondary" style={{ fontSize: "12px" }}>{s.reasons[0] || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
