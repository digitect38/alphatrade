import { useEffect, useState } from "react";
import OrderHistoryComponent from "../components/OrderHistory";
import StockSearch from "../components/StockSearch";
import { apiGet, apiPost } from "../hooks/useApi";
import type { OrderHistoryItem } from "../types";

const card = { background: "#fff", borderRadius: "8px", padding: "20px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" } as const;

export default function OrdersPage({ t: _t }: { t: (k: string) => string }) {
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [stockCode, setStockCode] = useState("005930");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState(10);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadOrders = () => {
    apiGet<OrderHistoryItem[]>("/order/history?limit=20")
      .then(setOrders)
      .catch(console.error);
  };

  useEffect(loadOrders, []);

  const submitOrder = async () => {
    setSubmitting(true);
    setMessage("");
    try {
      const result = await apiPost<{ order_id: string; status: string; message: string }>(
        "/order/execute",
        { stock_code: stockCode, side, quantity }
      );
      setMessage(`${result.status}: ${result.message} (${result.order_id})`);
      loadOrders();
    } catch (e) {
      setMessage(`Error: ${e}`);
    }
    setSubmitting(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={card}>
        <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{_t("order.manual")}</h3>
        <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
          <StockSearch
            value={stockCode}
            onChange={(code) => setStockCode(code)}
            placeholder={_t("common.placeholder.stockCode")}
          />
          <select
            value={side}
            onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}
            style={{ padding: "8px 12px", border: "1px solid #ddd", borderRadius: "6px", fontSize: "14px" }}
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            min={1}
            style={{ padding: "8px 12px", border: "1px solid #ddd", borderRadius: "6px", fontSize: "14px", width: "80px" }}
          />
          <button
            onClick={submitOrder}
            disabled={submitting}
            style={{
              padding: "8px 20px",
              background: side === "BUY" ? "#dc2626" : "#3b82f6",
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            {submitting ? "..." : _t(side === "BUY" ? "order.buy" : "order.sell")}
          </button>
        </div>
        {message && (
          <p style={{ marginTop: "8px", fontSize: "13px", color: message.startsWith("Error") ? "#dc2626" : "#16a34a" }}>
            {message}
          </p>
        )}
      </div>

      <OrderHistoryComponent orders={orders} />
    </div>
  );
}
