import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";

const card = { background: "#fff", borderRadius: "8px", padding: "20px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" } as const;

interface StockPrice {
  stock_code: string;
  stock_name: string;
  sector: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  news_count: number;
  stale?: boolean;
}

interface NewsItem {
  time: string;
  source: string;
  title: string;
  content: string;
  url: string;
}

interface MarketData {
  updated_at: string;
  count: number;
  stocks: StockPrice[];
}

export default function MarketPage({ t }: { t: (k: string) => string }) {
  const [data, setData] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [scanResult, setScanResult] = useState<string | null>(null);

  // News modal state
  const [newsOpen, setNewsOpen] = useState(false);
  const [newsStock, setNewsStock] = useState<{ code: string; name: string } | null>(null);
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);

  const fetchPrices = () => {
    setLoading(true);
    apiGet<MarketData>("/market/prices")
      .then(setData)
      .catch((e) => console.error(e))
      .finally(() => setLoading(false));
  };

  const runMorningScan = () => {
    setScanResult(t("common.loading"));
    apiPost<object>("/scanner/morning")
      .then((d) => setScanResult(JSON.stringify(d, null, 2)))
      .catch((e) => setScanResult(`Error: ${e}`));
  };

  const openNews = (code: string, name: string) => {
    setNewsStock({ code, name });
    setNewsOpen(true);
    setNewsLoading(true);
    apiGet<NewsItem[]>(`/market/news/${code}?limit=20`)
      .then(setNewsItems)
      .catch(() => setNewsItems([]))
      .finally(() => setNewsLoading(false));
  };

  useEffect(() => {
    fetchPrices();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(fetchPrices, 60000);
    return () => clearInterval(id);
  }, [autoRefresh]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ ...card, display: "flex", gap: "12px", alignItems: "center" }}>
        <button
          onClick={fetchPrices}
          disabled={loading}
          style={{ padding: "8px 20px", background: "#1a1a2e", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "14px" }}
        >
          {loading ? t("market.loading") : t("market.refresh")}
        </button>
        <label style={{ fontSize: "13px", display: "flex", alignItems: "center", gap: "6px" }}>
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          {t("market.autoRefresh")}
        </label>
        <button
          onClick={runMorningScan}
          style={{ padding: "8px 20px", background: "#dc2626", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "14px", marginLeft: "auto" }}
        >
          {t("market.morningScan")}
        </button>
        {data && (
          <span style={{ fontSize: "12px", color: "#888" }}>
            {new Date(data.updated_at).toLocaleString("ko-KR")} · {data.count}종목
          </span>
        )}
      </div>

      {data && data.stocks.length > 0 && (
        <div style={card}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #eee", textAlign: "left" }}>
                <th style={{ padding: "8px" }}>{t("th.name")}</th>
                <th style={{ padding: "8px" }}>{t("th.sector")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.price")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.change")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.changePct")}</th>
                <th style={{ padding: "8px", textAlign: "right" }}>{t("th.volume")}</th>
                <th style={{ padding: "8px", textAlign: "center" }}>{t("th.news")}</th>
              </tr>
            </thead>
            <tbody>
              {data.stocks.map((s) => {
                const color = s.change_pct > 0 ? "#dc2626" : s.change_pct < 0 ? "#3b82f6" : "#888";
                return (
                  <tr key={s.stock_code} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "8px" }}>
                      <span style={{ fontWeight: 600 }}>{s.stock_name}</span>
                      <span style={{ fontSize: "11px", color: "#888", marginLeft: "6px" }}>{s.stock_code}</span>
                      {s.stale && <span style={{ fontSize: "10px", color: "#f59e0b", marginLeft: "4px" }}>stale</span>}
                    </td>
                    <td style={{ padding: "8px", fontSize: "12px", color: "#666" }}>{s.sector}</td>
                    <td style={{ padding: "8px", textAlign: "right", fontWeight: 600 }}>
                      {s.price.toLocaleString()}
                    </td>
                    <td style={{ padding: "8px", textAlign: "right", color, fontWeight: 600 }}>
                      {s.change > 0 ? "+" : ""}{s.change.toLocaleString()}
                    </td>
                    <td style={{ padding: "8px", textAlign: "right", color, fontWeight: 700 }}>
                      {s.change_pct > 0 ? "+" : ""}{s.change_pct}%
                    </td>
                    <td style={{ padding: "8px", textAlign: "right", fontSize: "12px" }}>
                      {s.volume.toLocaleString()}
                    </td>
                    <td style={{ padding: "8px", textAlign: "center" }}>
                      {s.news_count > 0 ? (
                        <span
                          onClick={() => openNews(s.stock_code, s.stock_name)}
                          style={{
                            display: "inline-block",
                            background: "#ef4444",
                            color: "#fff",
                            borderRadius: "10px",
                            padding: "2px 8px",
                            fontSize: "11px",
                            fontWeight: 700,
                            cursor: "pointer",
                            minWidth: "20px",
                            textAlign: "center",
                          }}
                        >
                          {s.news_count}
                        </span>
                      ) : (
                        <span style={{ color: "#ccc", fontSize: "11px" }}>-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {scanResult && (
        <div style={card}>
          <h3 style={{ margin: "0 0 12px", fontSize: "14px" }}>{t("market.scanResult")}</h3>
          <pre style={{ fontSize: "12px", overflow: "auto", maxHeight: "300px", background: "#f5f5f5", padding: "12px", borderRadius: "6px" }}>
            {scanResult}
          </pre>
        </div>
      )}

      {/* News Modal */}
      {newsOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 1000,
          }}
          onClick={() => setNewsOpen(false)}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: "12px",
              padding: "24px",
              width: "700px",
              maxHeight: "80vh",
              overflowY: "auto",
              boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h2 style={{ margin: 0, fontSize: "18px" }}>
                {newsStock?.name} ({newsStock?.code}) {t("market.relatedNews")}
              </h2>
              <button
                onClick={() => setNewsOpen(false)}
                style={{ background: "none", border: "none", fontSize: "20px", cursor: "pointer", color: "#888" }}
              >
                ✕
              </button>
            </div>

            {newsLoading ? (
              <p style={{ color: "#888" }}>{t("common.loading")}</p>
            ) : newsItems.length === 0 ? (
              <p style={{ color: "#888" }}>{t("market.noNews")}</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {newsItems.map((n, i) => (
                  <div
                    key={i}
                    style={{
                      padding: "12px",
                      borderRadius: "8px",
                      background: "#f9f9f9",
                      borderLeft: "3px solid #1a1a2e",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ fontSize: "11px", color: "#888" }}>{n.source}</span>
                      <span style={{ fontSize: "11px", color: "#888" }}>
                        {new Date(n.time).toLocaleString("ko-KR")}
                      </span>
                    </div>
                    <a
                      href={n.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "#1a1a2e", fontWeight: 600, fontSize: "14px", textDecoration: "none" }}
                    >
                      {n.title}
                    </a>
                    {n.content && (
                      <p style={{ margin: "6px 0 0", fontSize: "12px", color: "#666", lineHeight: 1.5 }}>
                        {n.content}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
