import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";
import { orderStatusLabel } from "../lib/labels";
import { STATUS_COLORS, STATUS_BADGES } from "../lib/statusMapping";

interface Order {
  order_id: string;
  time: string;
  stock_code: string;
  side: string;
  quantity: number;
  filled_qty: number;
  filled_price: number | null;
  status: string;
  slippage: number | null;
}

// STATUS_COLORS, STATUS_BADGES imported from lib/statusMapping.ts

interface ExecQuality {
  total_fills: number;
  avg_slippage_bps?: number;
  median_slippage_bps?: number;
  p95_slippage_bps?: number;
  avg_fill_delay_sec?: number;
  high_slippage_count?: number;
  message?: string;
}

interface DailySummary {
  total_orders: number;
  filled: number;
  rejected: number;
  blocked: number;
  expired: number;
  fill_rate_pct: number;
  execution_quality: { avg_slippage_bps: number | null; avg_fill_delay_sec: number | null };
}

export default function ExecutionPage({ t: _t }: { t: (k: string) => string }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [reconciling, setReconciling] = useState(false);
  const [reconcileResult, setReconcileResult] = useState<Record<string, unknown> | null>(null);
  const [quality, setQuality] = useState<ExecQuality | null>(null);
  const [summary, setSummary] = useState<DailySummary | null>(null);

  const loadOrders = () => {
    apiGet<Order[]>("/order/history?limit=100").then(setOrders).catch(console.error);
    apiGet<ExecQuality>("/trading/execution-quality?days=30").then(setQuality).catch(() => {});
    apiGet<DailySummary>("/trading/order-summary").then(setSummary).catch(() => {});
  };

  const runReconcile = async () => {
    setReconciling(true);
    try {
      const result = await apiPost<Record<string, unknown>>("/trading/reconcile");
      setReconcileResult(result);
    } catch (e) {
      setReconcileResult({ error: String(e) } as Record<string, unknown>);
    }
    setReconciling(false);
  };

  useEffect(loadOrders, []);

  const filtered = filter === "all" ? orders :
    filter === "active" ? orders.filter((o) => ["SUBMITTED", "ACKED", "PARTIALLY_FILLED", "UNKNOWN"].includes(o.status)) :
    filter === "issues" ? orders.filter((o) => ["REJECTED", "BLOCKED", "FAILED", "UNKNOWN"].includes(o.status)) :
    orders.filter((o) => o.status === filter);

  const activeCnt = orders.filter((o) => ["SUBMITTED", "ACKED", "PARTIALLY_FILLED", "UNKNOWN"].includes(o.status)).length;
  const issueCnt = orders.filter((o) => ["REJECTED", "BLOCKED", "FAILED", "UNKNOWN"].includes(o.status)).length;

  return (
    <div className="page-content">
      {/* Header strip */}
      <div className="card flex gap-md items-center flex-wrap">
        <div className="flex gap-sm">
          {[
            { key: "all", label: `${_t("exec.all")} (${orders.length})` },
            { key: "active", label: `${_t("exec.active")} (${activeCnt})` },
            { key: "issues", label: `${_t("exec.issues")} (${issueCnt})` },
            { key: "FILLED", label: _t("exec.filled") },
          ].map((f) => (
            <button
              key={f.key}
              className={"btn btn-sm " + (filter === f.key ? "btn-primary" : "")}
              style={filter !== f.key ? { background: "#f0f0f0", color: "#333" } : undefined}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button className="btn btn-sm btn-primary ml-auto" onClick={loadOrders}>{_t("exec.refresh")}</button>
        <button className="btn btn-sm" style={{ background: "var(--color-accent-amber)", color: "#fff" }} onClick={runReconcile} disabled={reconciling}>
          {reconciling ? _t("exec.reconciling") : _t("exec.eodReconcile")}
        </button>
      </div>

      {/* Execution Quality Summary */}
      {(summary || quality) && (
        <div className="card">
          <h3 className="card-title">{_t("exec.qualityTitle")}</h3>
          <div className="metrics-grid metrics-grid-4" style={{ fontSize: 13 }}>
            {summary && (
              <>
                <div><div className="metric-label">{_t("exec.todayOrders")}</div><div className="font-bold">{summary.total_orders}</div></div>
                <div><div className="metric-label">{_t("exec.fillRate")}</div><div className={`font-bold ${summary.fill_rate_pct >= 90 ? "text-profit" : summary.fill_rate_pct >= 50 ? "text-warning" : "text-loss"}`}>{summary.fill_rate_pct}%</div></div>
                <div><div className="metric-label">{_t("exec.todaySlippage")}</div><div className="font-bold">{summary.execution_quality.avg_slippage_bps != null ? `${summary.execution_quality.avg_slippage_bps} bps` : "-"}</div></div>
                <div><div className="metric-label">{_t("exec.todayDelay")}</div><div className="font-bold">{summary.execution_quality.avg_fill_delay_sec != null ? `${summary.execution_quality.avg_fill_delay_sec}s` : "-"}</div></div>
              </>
            )}
            {quality && quality.total_fills > 0 && (
              <>
                <div><div className="metric-label">{_t("exec.totalFills30d")}</div><div className="font-bold">{quality.total_fills}</div></div>
                <div><div className="metric-label">{_t("exec.avgSlippage30d")}</div><div className="font-bold">{quality.avg_slippage_bps?.toFixed(1)} bps</div></div>
                <div><div className="metric-label">{_t("exec.p95Slippage")}</div><div className="font-bold">{quality.p95_slippage_bps?.toFixed(1)} bps</div></div>
                <div><div className="metric-label">{_t("exec.highSlippage")}</div><div className={`font-bold ${(quality.high_slippage_count || 0) > 0 ? "text-loss" : "text-profit"}`}>{quality.high_slippage_count || 0}{_t("common.count")}</div></div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Orders table */}
      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>{_t("th.status")}</th>
              <th>{_t("exec.orderId")}</th>
              <th>{_t("th.time")}</th>
              <th>{_t("th.code")}</th>
              <th>{_t("th.side")}</th>
              <th className="text-right">{_t("th.qty")}</th>
              <th className="text-right">{_t("exec.filledQty")}</th>
              <th className="text-right">{_t("th.price")}</th>
              <th className="text-right">{_t("exec.slippage")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={9} className="text-center text-muted" style={{ padding: "20px" }}>{_t("exec.noOrders")}</td></tr>
            )}
            {filtered.map((o) => (
              <tr key={o.order_id}>
                <td>
                  <span>{STATUS_BADGES[o.status] || "?"}</span>
                  <span className={`font-heavy ${STATUS_COLORS[o.status] || ""}`} style={{ marginLeft: "4px" }}>{orderStatusLabel(o.status, _t)}</span>
                </td>
                <td style={{ fontSize: "11px", fontFamily: "monospace" }}>{o.order_id}</td>
                <td style={{ fontSize: "11px" }}>{new Date(o.time).toLocaleString("ko-KR")}</td>
                <td className="font-bold">{o.stock_code}</td>
                <td className={o.side === "BUY" ? "text-up font-heavy" : "text-down font-heavy"}>{_t(o.side === "BUY" ? "signal.buy" : "signal.sell")}</td>
                <td className="text-right">{o.quantity}</td>
                <td className="text-right">{o.filled_qty}/{o.quantity}</td>
                <td className="text-right">{o.filled_price ? o.filled_price.toLocaleString() : "-"}</td>
                <td className="text-right">{o.slippage != null ? `${o.slippage.toFixed(2)}%` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Reconciliation Result */}
      {reconcileResult && (
        <div className="card">
          <h3 className="card-title">{_t("exec.reconciliationResult")}</h3>
          <pre style={{ fontSize: "12px", overflow: "auto", maxHeight: "200px", background: "#f5f5f5", padding: "12px", borderRadius: "6px" }}>
            {JSON.stringify(reconcileResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
