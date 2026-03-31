import type { Locale } from "../hooks/useLocale";

const menuItems = [
  { key: "command", labelKey: "nav.command", icon: "🎯" },
  { key: "dashboard", labelKey: "nav.dashboard", icon: "📊" },
  { key: "market", labelKey: "nav.market", icon: "💹" },
  { key: "trend", labelKey: "nav.trend", icon: "📉" },
  { key: "analysis", labelKey: "nav.analysis", icon: "📈" },
  { key: "backtest", labelKey: "nav.backtest", icon: "🧪" },
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
}

export default function Sidebar({ current, onNavigate, locale, onLocaleChange, t, isOpen = false, onClose }: Props) {
  return (
    <nav className={`sidebar ${isOpen ? "is-open" : ""}`}>
      <div className="sidebar-logo">AlphaTrade</div>
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
