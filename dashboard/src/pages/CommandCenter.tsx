import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";
import { useWebSocket } from "../hooks/useWebSocket";

interface Mover {
  stock_code: string;
  stock_name: string;
  sector: string;
  price: string;
  change_pct: string;
  volume: string;
}

interface EventCandidate {
  stock_code: string;
  stock_name: string;
  event_type: string;
  priority: number;
  details: Record<string, unknown>;
}

interface KillSwitchStatus {
  kill_switch: string;
  daily_loss_pct: number;
  session: { allowed: boolean; message: string };
  broker_failures: number;
}

const EVENT_ICONS: Record<string, string> = {
  price_spike: "📈",
  volume_surge: "📊",
  news_cluster: "📰",
  disclosure: "📋",
  sector_sympathy: "🔗",
  tradingview: "📺",
};

export default function CommandCenterPage({ t: _t }: { t: (k: string) => string }) {
  const [movers, setMovers] = useState<Mover[]>([]);
  const [candidates, setCandidates] = useState<EventCandidate[]>([]);
  const [killStatus, setKillStatus] = useState<KillSwitchStatus | null>(null);
  const [scanning, setScanning] = useState(false);

  const { connected } = useWebSocket({
    onTick: (tick) => {
      setMovers((prev) => {
        const existing = prev.filter((m) => m.stock_code !== tick.stock_code);
        const updated = [
          { stock_code: tick.stock_code, stock_name: "", sector: "", price: String(tick.price), change_pct: String(tick.change_pct), volume: String(tick.volume) },
          ...existing,
        ].sort((a, b) => Math.abs(Number(b.change_pct)) - Math.abs(Number(a.change_pct))).slice(0, 20);
        return updated;
      });
    },
  });

  const loadData = async () => {
    try {
      const [moversData, ksData] = await Promise.all([
        apiGet<{ movers: Mover[] }>("/market/movers?limit=20"),
        apiGet<KillSwitchStatus>("/trading/kill-switch/status"),
      ]);
      setMovers(moversData.movers || []);
      setKillStatus(ksData);
    } catch { /* ignore */ }
  };

  const runEventScan = async () => {
    setScanning(true);
    try {
      const data = await apiPost<{ candidates: EventCandidate[] }>("/scanner/events");
      setCandidates(data.candidates || []);
    } catch { /* ignore */ }
    setScanning(false);
  };

  useEffect(() => {
    loadData();
    runEventScan();
    const id = setInterval(() => { loadData(); runEventScan(); }, 30000);
    return () => clearInterval(id);
  }, []);

  const killActive = killStatus?.kill_switch === "active";

  return (
    <div className="page-content">
      {/* System Status Strip */}
      <div className="flex gap-lg items-center" style={{ padding: "8px 16px", background: killActive ? "var(--color-loss)" : "var(--color-profit)", borderRadius: "8px", color: "#fff", fontSize: "13px" }}>
        <span className="font-heavy">{connected ? "🟢 LIVE" : "🔴 OFFLINE"}</span>
        <span>|</span>
        <span>Kill: {killActive ? "🚨 ACTIVE" : "✅ OFF"}</span>
        <span>|</span>
        <span>Session: {killStatus?.session.allowed ? "✅ Open" : `❌ ${killStatus?.session.message || ""}`}</span>
        <span>|</span>
        <span>Daily P&L: {killStatus?.daily_loss_pct ?? 0}%</span>
        <span>|</span>
        <span>Broker Fails: {killStatus?.broker_failures ?? 0}/{killStatus ? 3 : "-"}</span>
        <span className="ml-auto flex gap-sm">
          <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.2)", color: "#fff" }} onClick={runEventScan} disabled={scanning}>
            {scanning ? "Scanning..." : "Scan Now"}
          </button>
          {!killActive && (
            <button className="btn btn-sm" style={{ background: "#fff", color: "var(--color-loss)" }} onClick={() => { if (confirm("Kill switch 활성화?")) apiPost("/trading/kill-switch/activate").then(loadData); }}>
              Kill Switch
            </button>
          )}
          {killActive && (
            <button className="btn btn-sm" style={{ background: "#fff", color: "var(--color-profit)" }} onClick={() => apiPost("/trading/kill-switch/deactivate").then(loadData)}>
              Resume
            </button>
          )}
        </span>
      </div>

      <div className="metrics-grid metrics-grid-2">
        {/* Left: Live Movers */}
        <div className="card">
          <h3 className="card-title">Live Movers</h3>
          <div className="flex flex-col" style={{ maxHeight: "500px", overflowY: "auto" }}>
            {movers.length === 0 && <div className="text-muted p-xl text-center">No data</div>}
            {movers.map((m) => {
              const pct = Number(m.change_pct);
              const cls = pct > 0 ? "text-up" : pct < 0 ? "text-down" : "text-neutral";
              return (
                <div key={m.stock_code} className="flex justify-between items-center" style={{ padding: "6px 0", borderBottom: "1px solid var(--color-border-light)" }}>
                  <div>
                    <span className="font-bold">{m.stock_name || m.stock_code}</span>
                    <span className="text-secondary" style={{ fontSize: "11px", marginLeft: "6px" }}>{m.stock_code}</span>
                  </div>
                  <div className="flex gap-lg items-center">
                    <span className="font-bold">{Number(m.price).toLocaleString()}</span>
                    <span className={`font-heavy ${cls}`} style={{ minWidth: "60px", textAlign: "right" }}>
                      {pct > 0 ? "+" : ""}{pct.toFixed(2)}%
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Event Candidates */}
        <div className="card">
          <h3 className="card-title">Event Candidates ({candidates.length})</h3>
          <div className="flex flex-col" style={{ maxHeight: "500px", overflowY: "auto" }}>
            {candidates.length === 0 && <div className="text-muted p-xl text-center">No events detected</div>}
            {candidates.map((c, i) => (
              <div key={`${c.stock_code}-${i}`} className="flex justify-between items-center" style={{ padding: "8px 0", borderBottom: "1px solid var(--color-border-light)" }}>
                <div>
                  <span style={{ marginRight: "6px" }}>{EVENT_ICONS[c.event_type] || "⚡"}</span>
                  <span className="font-bold">{c.stock_name || c.stock_code}</span>
                  <span className="text-secondary" style={{ fontSize: "11px", marginLeft: "6px" }}>{c.event_type}</span>
                </div>
                <div className="flex gap-md items-center">
                  <span className="font-heavy" style={{ color: c.priority >= 50 ? "var(--color-loss)" : "var(--color-warning)" }}>
                    P{c.priority.toFixed(0)}
                  </span>
                  <span className="text-secondary" style={{ fontSize: "11px" }}>
                    {Object.entries(c.details).map(([k, v]) => `${k}: ${v}`).join(", ").slice(0, 40)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
