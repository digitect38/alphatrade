import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";

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

const STATUS_COLORS: Record<string, string> = {
  CREATED: "text-neutral",
  VALIDATED: "text-neutral",
  SUBMITTED: "text-warning",
  ACKED: "text-warning",
  PARTIALLY_FILLED: "text-warning",
  FILLED: "text-profit",
  CANCELLED: "text-secondary",
  REJECTED: "text-loss",
  BLOCKED: "text-loss",
  FAILED: "text-loss",
  UNKNOWN: "text-loss",
  EXPIRED: "text-secondary",
};

const STATUS_BADGES: Record<string, string> = {
  FILLED: "✅", PARTIALLY_FILLED: "⏳", SUBMITTED: "📤", ACKED: "📥",
  REJECTED: "❌", BLOCKED: "🚫", FAILED: "💥", UNKNOWN: "❓",
  CANCELLED: "🚪", EXPIRED: "⏰", CREATED: "📝", VALIDATED: "✔️",
};

export default function ExecutionPage({ t: _t }: { t: (k: string) => string }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [reconciling, setReconciling] = useState(false);
  const [reconcileResult, setReconcileResult] = useState<Record<string, unknown> | null>(null);

  const loadOrders = () => {
    apiGet<Order[]>("/order/history?limit=100").then(setOrders).catch(console.error);
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
            { key: "all", label: `All (${orders.length})` },
            { key: "active", label: `Active (${activeCnt})` },
            { key: "issues", label: `Issues (${issueCnt})` },
            { key: "FILLED", label: "Filled" },
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
        <button className="btn btn-sm btn-primary ml-auto" onClick={loadOrders}>Refresh</button>
        <button className="btn btn-sm" style={{ background: "var(--color-accent-amber)", color: "#fff" }} onClick={runReconcile} disabled={reconciling}>
          {reconciling ? "Reconciling..." : "EOD Reconcile"}
        </button>
      </div>

      {/* Orders table */}
      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Order ID</th>
              <th>Time</th>
              <th>Code</th>
              <th>Side</th>
              <th className="text-right">Qty</th>
              <th className="text-right">Filled</th>
              <th className="text-right">Price</th>
              <th className="text-right">Slippage</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={9} className="text-center text-muted" style={{ padding: "20px" }}>No orders</td></tr>
            )}
            {filtered.map((o) => (
              <tr key={o.order_id}>
                <td>
                  <span>{STATUS_BADGES[o.status] || "?"}</span>
                  <span className={`font-heavy ${STATUS_COLORS[o.status] || ""}`} style={{ marginLeft: "4px" }}>{o.status}</span>
                </td>
                <td style={{ fontSize: "11px", fontFamily: "monospace" }}>{o.order_id}</td>
                <td style={{ fontSize: "11px" }}>{new Date(o.time).toLocaleString("ko-KR")}</td>
                <td className="font-bold">{o.stock_code}</td>
                <td className={o.side === "BUY" ? "text-up font-heavy" : "text-down font-heavy"}>{o.side}</td>
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
          <h3 className="card-title">Reconciliation Result</h3>
          <pre style={{ fontSize: "12px", overflow: "auto", maxHeight: "200px", background: "#f5f5f5", padding: "12px", borderRadius: "6px" }}>
            {JSON.stringify(reconcileResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
