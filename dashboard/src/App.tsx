import { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import { ToastProvider } from "./components/Toast";
import { useLocale } from "./hooks/useLocale";
import AnalysisPage from "./pages/Analysis";
import BacktestPage from "./pages/Backtest";
import DashboardPage from "./pages/Dashboard";
import MarketPage from "./pages/Market";
import OrdersPage from "./pages/Orders";
import TrendPage from "./pages/Trend";

const titleKeys: Record<string, string> = {
  dashboard: "title.dashboard",
  market: "title.market",
  trend: "title.trend",
  analysis: "title.analysis",
  backtest: "title.backtest",
  orders: "title.orders",
};

export default function App() {
  const [page, setPage] = useState(window.location.hash.slice(1) || "dashboard");
  const { locale, setLocale, t } = useLocale();

  useEffect(() => {
    const onHash = () => setPage(window.location.hash.slice(1) || "dashboard");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (p: string) => {
    window.location.hash = p;
  };

  return (
    <ToastProvider>
      <div className="app-layout">
        <Sidebar current={page} onNavigate={navigate} locale={locale} onLocaleChange={setLocale} t={t} />
        <main className="app-main">
          <h1 className="page-title">{t(titleKeys[page] || "title.dashboard")}</h1>
          {page === "dashboard" && <DashboardPage t={t} />}
          {page === "market" && <MarketPage t={t} />}
          {page === "trend" && <TrendPage t={t} />}
          {page === "analysis" && <AnalysisPage t={t} />}
          {page === "backtest" && <BacktestPage t={t} />}
          {page === "orders" && <OrdersPage t={t} />}
        </main>
      </div>
    </ToastProvider>
  );
}
