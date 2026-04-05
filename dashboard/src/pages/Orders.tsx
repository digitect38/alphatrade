import { useEffect, useState, type MutableRefObject } from "react";
import OrderHistoryComponent from "../components/OrderHistory";
import StockSearch from "../components/StockSearch";
import { apiGet, apiPost } from "../hooks/useApi";
import type { OrderHistoryItem } from "../types";

export default function OrdersPage({ t: _t, onStockChangeRef }: { t: (k: string) => string; onStockChangeRef?: MutableRefObject<((code: string, name: string) => void) | null> }) {
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [stockCode, setStockCode] = useState("005930");

  // Register callback so sidebar can change stock on this page
  useEffect(() => {
    if (onStockChangeRef) {
      onStockChangeRef.current = (code) => setStockCode(code);
      return () => { onStockChangeRef.current = null; };
    }
  }, [onStockChangeRef]);
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
    <div className="page-content">
      <div className="card">
        <h3 className="card-title">{_t("order.manual")}</h3>
        <div className="flex gap-md items-center flex-wrap">
          <StockSearch
            value={stockCode}
            onChange={(code) => setStockCode(code)}
            placeholder={_t("common.placeholder.stockCode")}
            t={_t}
          />
          <select
            value={side}
            onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}
            className="select"
          >
            <option value="BUY">{_t("signal.buy")}</option>
            <option value="SELL">{_t("signal.sell")}</option>
          </select>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            min={1}
            className="input"
            style={{ width: "80px" }}
          />
          <button
            onClick={submitOrder}
            disabled={submitting}
            className={"btn " + (side === "BUY" ? "btn-danger" : "btn-primary")}
            style={{ background: side === "BUY" ? "var(--color-up)" : "var(--color-down)" }}
          >
            {submitting ? "..." : _t(side === "BUY" ? "order.buy" : "order.sell")}
          </button>
        </div>
        {message && (
          <p className={message.startsWith("Error") ? "text-loss" : "text-profit"} style={{ marginTop: "8px", fontSize: "13px" }}>
            {message}
          </p>
        )}
      </div>

      <OrderHistoryComponent orders={orders} t={_t} />
    </div>
  );
}
