import type { PortfolioStatus } from "../types";

function fmt(n: number) {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

export default function PortfolioCard({ data, t }: { data: PortfolioStatus; t: (k: string) => string }) {
  return (
    <div>
      <div className="metrics-grid metrics-grid-4" style={{ marginBottom: "20px" }}>
        <div className="card">
          <div className="metric-label">{t("dash.totalValue")}</div>
          <div className="metric-value">{fmt(data.total_value)}</div>
          <div className="metric-unit">{t("common.won")}</div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.cash")}</div>
          <div className="metric-value">{fmt(data.cash)}</div>
          <div className="metric-unit">{t("common.won")}</div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.unrealizedPnl")}</div>
          <div className={`metric-value ${data.unrealized_pnl >= 0 ? "text-profit" : "text-loss"}`}>
            {data.unrealized_pnl >= 0 ? "+" : ""}{fmt(data.unrealized_pnl)}{t("common.won")}
          </div>
        </div>
        <div className="card">
          <div className="metric-label">{t("dash.return")}</div>
          <div className={`metric-value ${data.total_return_pct >= 0 ? "text-profit" : "text-loss"}`}>
            {data.total_return_pct >= 0 ? "+" : ""}{data.total_return_pct}%
          </div>
        </div>
      </div>

      {data.positions.length > 0 && (
        <div className="card">
          <h3 className="card-title">{t("dash.positions")} ({data.positions_count})</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("th.code")}</th>
                <th>{t("th.name")}</th>
                <th className="text-right">{t("th.qty")}</th>
                <th className="text-right">{t("th.avgPrice")}</th>
                <th className="text-right">{t("th.current")}</th>
                <th className="text-right">{t("th.pnl")}</th>
                <th className="text-right">{t("th.weight")}</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p) => (
                <tr key={p.stock_code}>
                  <td className="font-bold">{p.stock_code}</td>
                  <td>{p.stock_name || "-"}</td>
                  <td className="text-right">{p.quantity}</td>
                  <td className="text-right">{fmt(p.avg_price)}</td>
                  <td className="text-right">{p.current_price ? fmt(p.current_price) : "-"}</td>
                  <td className={`text-right font-heavy ${(p.unrealized_pnl_pct ?? 0) >= 0 ? "text-profit" : "text-loss"}`}>
                    {p.unrealized_pnl_pct != null ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct}%` : "-"}
                  </td>
                  <td className="text-right">{p.weight ? `${(p.weight * 100).toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
