import type { Locale } from "../hooks/useLocale";
import type { RecentStock } from "../hooks/useRecentStocks";

const menuItems = [
  { key: "command", labelKey: "nav.command", icon: "🎯" },
  { key: "dashboard", labelKey: "nav.dashboard", icon: "📊" },
  { key: "market", labelKey: "nav.market", icon: "💹" },
  { key: "trend", labelKey: "nav.trend", icon: "📉" },
  { key: "analysis", labelKey: "nav.analysis", icon: "📈" },
  { key: "backtest", labelKey: "nav.backtest", icon: "🧪" },
  { key: "risk", labelKey: "nav.risk", icon: "🛡️" },
  { key: "execution", labelKey: "nav.execution", icon: "⚡" },
  { key: "orders", labelKey: "nav.orders", icon: "📋" },
];

interface Props {
  current: string;
  onNavigate: (page: string) => void;
  locale: Locale;
  onLocaleChange: (l: Locale) => void;
  t: (key: string) => string;
  isOpen?: boolean;
  onClose?: () => void;
  tradingMode?: string;
  recentStocks?: RecentStock[];
}

export default function Sidebar({ current, onNavigate, locale, onLocaleChange, t, isOpen = false, onClose, tradingMode, recentStocks }: Props) {
  const isLive = tradingMode === "live";
  return (
    <nav className={`sidebar ${isOpen ? "is-open" : ""} ${isLive ? "sidebar-live" : ""}`}>
      <div className="sidebar-logo">AlphaTrade</div>
      {isLive && (
        <div className="sidebar-live-banner">
          LIVE TRADING
        </div>
      )}
      {!isLive && tradingMode && (
        <div className="sidebar-paper-banner">
          PAPER MODE
        </div>
      )}
      {menuItems.map((m) => (
        <div
          key={m.key}
          className={`sidebar-item ${current === m.key ? "active" : ""}`}
          onClick={() => {
            onNavigate(m.key);
            onClose?.();
          }}
        >
          <span>{m.icon}</span>
          <span>{t(m.labelKey)}</span>
        </div>
      ))}
      {recentStocks && recentStocks.length > 0 && (
        <div className="sidebar-recent">
          <div className="sidebar-recent-title">{t("nav.recentStocks")}</div>
          {recentStocks.map((stock) => (
            <div
              key={stock.code}
              className="sidebar-recent-item"
              onClick={() => {
                // Stay on current page, just switch stock
                const base = current.startsWith("analysis") ? "analysis"
                  : current.startsWith("asset") ? "asset"
                  : current === "backtest" ? "asset"
                  : "asset";
                onNavigate(`${base}/${stock.code}`);
                onClose?.();
              }}
            >
              <span className="sidebar-recent-name">{stock.name}</span>
              <span className="sidebar-recent-code">{stock.code}</span>
            </div>
          ))}
        </div>
      )}
      <div className="sidebar-lang">
        <button className={`lang-btn ${locale === "ko" ? "active" : ""}`} onClick={() => onLocaleChange("ko")}>
          한국어
        </button>
        <button className={`lang-btn ${locale === "en" ? "active" : ""}`} onClick={() => onLocaleChange("en")}>
          English
        </button>
      </div>
    </nav>
  );
}
