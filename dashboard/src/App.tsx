import { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import { ToastProvider } from "./components/Toast";
import { useLocale } from "./hooks/useLocale";
import AnalysisPage from "./pages/Analysis";
import BacktestPage from "./pages/Backtest";
import CommandCenterPage from "./pages/CommandCenter";
import DashboardPage from "./pages/Dashboard";
import ExecutionPage from "./pages/Execution";
import MarketPage from "./pages/Market";
import OrdersPage from "./pages/Orders";
import TrendPage from "./pages/Trend";

const titleKeys: Record<string, string> = {
  command: "title.command",
  dashboard: "title.dashboard",
  market: "title.market",
  trend: "title.trend",
  analysis: "title.analysis",
  backtest: "title.backtest",
  execution: "title.execution",
  orders: "title.orders",
};

export default function App() {
  const [page, setPage] = useState(window.location.hash.slice(1) || "command");
  const { locale, setLocale, t } = useLocale();

  useEffect(() => {
    const onHash = () => setPage(window.location.hash.slice(1) || "command");
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
          <h1 className="page-title">{t(titleKeys[page] || "title.command")}</h1>
          {page === "command" && <CommandCenterPage t={t} />}
          {page === "dashboard" && <DashboardPage t={t} />}
          {page === "market" && <MarketPage t={t} />}
          {page === "trend" && <TrendPage t={t} />}
          {page === "analysis" && <AnalysisPage t={t} />}
          {page === "backtest" && <BacktestPage t={t} />}
          {page === "execution" && <ExecutionPage t={t} />}
          {page === "orders" && <OrdersPage t={t} />}
        </main>
      </div>
    </ToastProvider>
  );
}
