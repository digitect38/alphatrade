import type { OrderHistoryItem } from "../types";
import { orderStatusLabel } from "../lib/labels";

export default function OrderHistory({ orders, t }: { orders: OrderHistoryItem[]; t: (k: string) => string }) {
  return (
    <div className="card">
      <h3 className="card-title">{t("order.history")}</h3>
      {orders.length === 0 ? (
        <p className="text-secondary">{t("order.noOrders")}</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("th.time")}</th>
              <th>{t("th.code")}</th>
              <th>{t("th.side")}</th>
              <th className="text-right">{t("th.qty")}</th>
              <th className="text-right">{t("th.price")}</th>
              <th>{t("th.status")}</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.order_id}>
                <td style={{ fontSize: "12px" }}>{new Date(o.time).toLocaleString("ko-KR")}</td>
                <td className="font-bold">{o.stock_code}</td>
                <td className={`font-bold ${o.side === "BUY" ? "text-up" : "text-down"}`}>{t(o.side === "BUY" ? "signal.buy" : "signal.sell")}</td>
                <td className="text-right">{o.filled_qty}/{o.quantity}</td>
                <td className="text-right">{o.filled_price ? o.filled_price.toLocaleString() : "-"}</td>
                <td className={`font-bold ${o.status === "FILLED" ? "text-profit" : o.status === "FAILED" ? "text-loss" : "text-secondary"}`}>
                  {orderStatusLabel(o.status, t)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
