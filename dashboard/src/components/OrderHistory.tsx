import type { OrderHistoryItem } from "../types";

export default function OrderHistory({ orders }: { orders: OrderHistoryItem[] }) {
  return (
    <div className="card">
      <h3 className="card-title">Order History</h3>
      {orders.length === 0 ? (
        <p className="text-secondary">No orders yet</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Code</th>
              <th>Side</th>
              <th className="text-right">Qty</th>
              <th className="text-right">Price</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.order_id}>
                <td style={{ fontSize: "12px" }}>{new Date(o.time).toLocaleString("ko-KR")}</td>
                <td className="font-bold">{o.stock_code}</td>
                <td className={`font-bold ${o.side === "BUY" ? "text-up" : "text-down"}`}>{o.side}</td>
                <td className="text-right">{o.filled_qty}/{o.quantity}</td>
                <td className="text-right">{o.filled_price ? o.filled_price.toLocaleString() : "-"}</td>
                <td className={`font-bold ${o.status === "FILLED" ? "text-profit" : o.status === "FAILED" ? "text-loss" : "text-secondary"}`}>
                  {o.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
