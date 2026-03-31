import { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import { ToastProvider } from "./components/Toast";
import { apiGet } from "./hooks/useApi";
import { useLocale } from "./hooks/useLocale";
import AnalysisPage from "./pages/Analysis";
import AssetDetailPage from "./pages/AssetDetail";
import BacktestPage from "./pages/Backtest";
import CommandCenterPage from "./pages/CommandCenter";
import DashboardPage from "./pages/Dashboard";
import ExecutionPage from "./pages/Execution";
import MarketPage from "./pages/Market";
import OrdersPage from "./pages/Orders";
import RiskPage from "./pages/Risk";
import TrendPage from "./pages/Trend";

const titleKeys: Record<string, string> = {
  command: "title.command",
  dashboard: "title.dashboard",
  market: "title.market",
  trend: "title.trend",
  analysis: "title.analysis",
  backtest: "title.backtest",
  risk: "title.risk",
  execution: "title.execution",
  orders: "title.orders",
  asset: "title.asset",
};

export default function App() {
  const [page, setPage] = useState(window.location.hash.slice(1) || "command");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [tradingMode, setTradingMode] = useState<string>("paper");
  const { locale, setLocale, t } = useLocale();

  useEffect(() => {
    apiGet<{ mode: string }>("/trading/mode").then((d) => setTradingMode(d.mode)).catch(() => {});
    const modeInterval = setInterval(() => {
      apiGet<{ mode: string }>("/trading/mode").then((d) => setTradingMode(d.mode)).catch(() => {});
    }, 10000);
    return () => clearInterval(modeInterval);
  }, []);

  useEffect(() => {
    const onHash = () => {
      setPage(window.location.hash.slice(1) || "command");
      setMobileNavOpen(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (p: string) => {
    window.location.hash = p;
  };

  const pageKey = page.startsWith("asset") ? "asset" : page.startsWith("analysis") ? "analysis" : page;

  return (
    <ToastProvider>
      <div className="app-layout">
        <button
          className="mobile-nav-toggle"
          onClick={() => setMobileNavOpen((open) => !open)}
          aria-label={t("nav.menu")}
          aria-expanded={mobileNavOpen}
        >
          <span>☰</span>
          <span>{t("nav.menu")}</span>
        </button>
        {mobileNavOpen ? <button className="mobile-nav-backdrop" aria-label={t("nav.closeMenu")} onClick={() => setMobileNavOpen(false)} /> : null}
        <Sidebar
          current={page}
          onNavigate={navigate}
          locale={locale}
          onLocaleChange={setLocale}
          t={t}
          isOpen={mobileNavOpen}
          onClose={() => setMobileNavOpen(false)}
          tradingMode={tradingMode}
        />
        <main className={`app-main ${tradingMode === "live" ? "app-main-live" : "app-main-paper"}`}>
          <h1 className="page-title">{t(titleKeys[pageKey] || "title.command")}</h1>
          {page === "command" && <CommandCenterPage t={t} />}
          {page === "dashboard" && <DashboardPage t={t} />}
          {page === "market" && <MarketPage t={t} />}
          {page === "trend" && <TrendPage t={t} />}
          {page.startsWith("analysis") && <AnalysisPage t={t} initialCode={page.includes("/") ? page.split("/")[1] : undefined} />}
          {page === "backtest" && <BacktestPage t={t} />}
          {page === "risk" && <RiskPage t={t} />}
          {page === "execution" && <ExecutionPage t={t} />}
          {page === "orders" && <OrdersPage t={t} />}
          {page.startsWith("asset") && <AssetDetailPage t={t} route={page} />}
        </main>
      </div>
    </ToastProvider>
  );
}
