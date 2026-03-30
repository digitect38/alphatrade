import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";

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
    <div className="page-content">
      <div className="card flex gap-md items-center">
        <button onClick={fetchPrices} disabled={loading} className="btn btn-primary">
          {loading ? t("market.loading") : t("market.refresh")}
        </button>
        <label className="flex items-center gap-sm" style={{ fontSize: "13px" }}>
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          {t("market.autoRefresh")}
        </label>
        <button onClick={runMorningScan} className="btn btn-danger ml-auto">
          {t("market.morningScan")}
        </button>
        {data && (
          <span className="text-secondary" style={{ fontSize: "12px" }}>
            {new Date(data.updated_at).toLocaleString("ko-KR")} · {data.count}종목
          </span>
        )}
      </div>

      {data && data.stocks.length > 0 && (
        <div className="card">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("th.name")}</th>
                <th>{t("th.sector")}</th>
                <th className="text-right">{t("th.price")}</th>
                <th className="text-right">{t("th.change")}</th>
                <th className="text-right">{t("th.changePct")}</th>
                <th className="text-right">{t("th.volume")}</th>
                <th className="text-center">{t("th.news")}</th>
              </tr>
            </thead>
            <tbody>
              {data.stocks.map((s) => {
                const colorClass = s.change_pct > 0 ? "text-up" : s.change_pct < 0 ? "text-down" : "text-neutral";
                return (
                  <tr key={s.stock_code}>
                    <td>
                      <span className="font-bold">{s.stock_name}</span>
                      <span className="text-secondary" style={{ fontSize: "11px", marginLeft: "6px" }}>{s.stock_code}</span>
                      {s.stale && <span className="text-warning" style={{ fontSize: "10px", marginLeft: "4px" }}>stale</span>}
                    </td>
                    <td className="text-secondary" style={{ fontSize: "12px" }}>{s.sector}</td>
                    <td className="text-right font-bold">
                      {s.price.toLocaleString()}
                    </td>
                    <td className={"text-right font-bold " + colorClass}>
                      {s.change > 0 ? "+" : ""}{s.change.toLocaleString()}
                    </td>
                    <td className={"text-right font-heavy " + colorClass}>
                      {s.change_pct > 0 ? "+" : ""}{s.change_pct}%
                    </td>
                    <td className="text-right" style={{ fontSize: "12px" }}>
                      {s.volume.toLocaleString()}
                    </td>
                    <td className="text-center">
                      {s.news_count > 0 ? (
                        <span
                          onClick={() => openNews(s.stock_code, s.stock_name)}
                          className="badge badge-red"
                        >
                          {s.news_count}
                        </span>
                      ) : (
                        <span className="text-muted" style={{ fontSize: "11px" }}>-</span>
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
        <div className="card">
          <h3 className="card-title">{t("market.scanResult")}</h3>
          <pre style={{ fontSize: "12px", overflow: "auto", maxHeight: "300px", background: "#f5f5f5", padding: "12px", borderRadius: "6px" }}>
            {scanResult}
          </pre>
        </div>
      )}

      {/* News Modal */}
      {newsOpen && (
        <div className="modal-overlay" onClick={() => setNewsOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ fontSize: "18px" }}>
                {newsStock?.name} ({newsStock?.code}) {t("market.relatedNews")}
              </h2>
              <button onClick={() => setNewsOpen(false)} className="modal-close">
                ✕
              </button>
            </div>

            {newsLoading ? (
              <p className="text-secondary">{t("common.loading")}</p>
            ) : newsItems.length === 0 ? (
              <p className="text-secondary">{t("market.noNews")}</p>
            ) : (
              <div className="flex flex-col gap-md">
                {newsItems.map((n, i) => (
                  <div key={i} className="news-item">
                    <div className="flex justify-between mb-sm">
                      <span className="text-secondary" style={{ fontSize: "11px" }}>{n.source}</span>
                      <span className="text-secondary" style={{ fontSize: "11px" }}>
                        {new Date(n.time).toLocaleString("ko-KR")}
                      </span>
                    </div>
                    <a href={n.url} target="_blank" rel="noopener noreferrer">
                      {n.title}
                    </a>
                    {n.content && (
                      <p className="text-secondary" style={{ margin: "6px 0 0", fontSize: "12px", lineHeight: 1.5 }}>
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
