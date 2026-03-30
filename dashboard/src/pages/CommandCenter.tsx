import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../hooks/useApi";
import { useWebSocket } from "../hooks/useWebSocket";
import type { HealthStatus, OrderHistoryItem } from "../types";

interface Mover {
  stock_code: string;
  stock_name: string;
  sector: string;
  price: number | string;
  change_pct: number | string;
  volume: number | string;
  stale?: boolean;
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
  broker_limit?: number;
}

interface NewsItem {
  time: string;
  source: string;
  title: string;
  content: string;
  url: string;
}

type CandidateLane = "eligible" | "blocked" | "watching" | "executed";

interface CandidateCard extends EventCandidate {
  lane: CandidateLane;
  summary: string;
  recentOrder: OrderHistoryItem | null;
  riskReason: string | null;
}

interface IncidentItem {
  id: string;
  severity: "critical" | "warning" | "info";
  title: string;
  summary: string;
  symbol?: string;
  action: string;
}

const EVENT_LABELS: Record<string, string> = {
  price_spike: "Price Spike",
  volume_surge: "Volume Surge",
  news_cluster: "News Cluster",
  disclosure: "Disclosure",
  sector_sympathy: "Sector Sympathy",
  tradingview: "TradingView",
};

const LANE_TITLES: Record<CandidateLane, string> = {
  eligible: "Eligible",
  blocked: "Blocked",
  watching: "Watching",
  executed: "Executed",
};

const EXECUTION_ISSUE_STATUSES = new Set(["REJECTED", "BLOCKED", "FAILED", "UNKNOWN"]);
const EXECUTION_ACTIVE_STATUSES = new Set(["SUBMITTED", "ACKED", "PARTIALLY_FILLED", "FILLED"]);

export default function CommandCenterPage({ t: _t }: { t: (k: string) => string }) {
  const [movers, setMovers] = useState<Mover[]>([]);
  const [candidates, setCandidates] = useState<EventCandidate[]>([]);
  const [killStatus, setKillStatus] = useState<KillSwitchStatus | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [selectedLane, setSelectedLane] = useState<CandidateLane>("eligible");
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [scanning, setScanning] = useState(false);

  const { connected, lastTick } = useWebSocket({
    onTick: (tick) => {
      setMovers((prev) => {
        const next = [...prev];
        const index = next.findIndex((item) => item.stock_code === tick.stock_code);
        const existing = index >= 0 ? next[index] : {
          stock_code: tick.stock_code,
          stock_name: tick.stock_code,
          sector: "",
          price: tick.price,
          change_pct: tick.change_pct,
          volume: tick.volume,
        };
        const updated = {
          ...existing,
          price: tick.price,
          change_pct: tick.change_pct,
          volume: tick.volume,
          stale: false,
        };
        if (index >= 0) next[index] = updated;
        else next.unshift(updated);
        return next
          .sort((a, b) => Math.abs(toNumber(b.change_pct)) - Math.abs(toNumber(a.change_pct)))
          .slice(0, 20);
      });
    },
  });

  const loadData = async () => {
    try {
      const [moversData, ksData, healthData, orderData] = await Promise.all([
        apiGet<{ movers: Mover[] }>("/market/movers?limit=20"),
        apiGet<KillSwitchStatus>("/trading/kill-switch/status"),
        apiGet<HealthStatus>("/health"),
        apiGet<OrderHistoryItem[]>("/order/history?limit=50"),
      ]);
      setMovers(moversData.movers || []);
      setKillStatus(ksData);
      setHealth(healthData);
      setOrders(orderData || []);
    } catch {
      // keep previous state on transient failures
    }
  };

  const runEventScan = async () => {
    setScanning(true);
    try {
      const data = await apiPost<{ candidates: EventCandidate[] }>("/scanner/events");
      setCandidates(data.candidates || []);
    } catch {
      // ignore transient failures
    } finally {
      setScanning(false);
    }
  };

  useEffect(() => {
    void loadData();
    void runEventScan();
    const id = setInterval(() => {
      void loadData();
      void runEventScan();
    }, 30000);
    return () => clearInterval(id);
  }, []);

  const enrichedCandidates = useMemo<CandidateCard[]>(() => {
    const killActive = killStatus?.kill_switch === "active";
    const sessionBlocked = killStatus ? !killStatus.session.allowed : false;
    const brokerBlocked = (killStatus?.broker_failures ?? 0) >= (killStatus?.broker_limit ?? 3);

    return candidates
      .map((candidate) => {
        const recentOrder = orders.find((order) => order.stock_code === candidate.stock_code) || null;
        const summary = summarizeDetails(candidate.details);

        let lane: CandidateLane = "watching";
        let riskReason: string | null = null;

        if (recentOrder && EXECUTION_ACTIVE_STATUSES.has(recentOrder.status)) {
          lane = "executed";
        } else if (killActive) {
          lane = "blocked";
          riskReason = "Kill switch active";
        } else if (sessionBlocked) {
          lane = "blocked";
          riskReason = killStatus?.session.message || "Trading session blocked";
        } else if (brokerBlocked) {
          lane = "blocked";
          riskReason = "Broker failure threshold reached";
        } else if (candidate.priority >= 75) {
          lane = "eligible";
        } else {
          lane = "watching";
        }

        if (recentOrder && EXECUTION_ISSUE_STATUSES.has(recentOrder.status)) {
          lane = "blocked";
          riskReason = `Execution issue: ${recentOrder.status}`;
        }

        return { ...candidate, lane, summary, recentOrder, riskReason };
      })
      .sort((a, b) => b.priority - a.priority);
  }, [candidates, killStatus, orders]);

  const incidents = useMemo<IncidentItem[]>(() => {
    const list: IncidentItem[] = [];

    if (!connected) {
      list.push({
        id: "ws-offline",
        severity: "critical",
        title: "Realtime feed offline",
        summary: "Dashboard WebSocket disconnected. Live state may be stale.",
        action: "Check feed",
      });
    }

    if (health && health.status !== "ok") {
      list.push({
        id: "api-health",
        severity: "critical",
        title: "API health degraded",
        summary: `API=${health.status} DB=${health.db} Redis=${health.redis}`,
        action: "Open system",
      });
    }

    if (killStatus?.kill_switch === "active") {
      list.push({
        id: "kill-switch",
        severity: "critical",
        title: "Kill switch active",
        summary: "All new orders are blocked until operator resumes trading.",
        action: "Review block",
      });
    }

    if (killStatus && !killStatus.session.allowed) {
      list.push({
        id: "session-block",
        severity: "warning",
        title: "Session blocked",
        summary: killStatus.session.message || "Outside allowed trading window.",
        action: "Inspect session",
      });
    }

    if ((killStatus?.broker_failures ?? 0) > 0) {
      list.push({
        id: "broker-failures",
        severity: (killStatus?.broker_failures ?? 0) >= (killStatus?.broker_limit ?? 3) ? "critical" : "warning",
        title: "Broker failures detected",
        summary: `${killStatus?.broker_failures ?? 0}/${killStatus?.broker_limit ?? 3} recent failures recorded.`,
        action: "Reconcile",
      });
    }

    orders
      .filter((order) => EXECUTION_ISSUE_STATUSES.has(order.status))
      .slice(0, 4)
      .forEach((order) => {
        list.push({
          id: `order-${order.order_id}`,
          severity: "warning",
          title: `Order ${order.status}`,
          summary: `${order.stock_code} ${order.side} ${order.filled_qty}/${order.quantity}`,
          symbol: order.stock_code,
          action: "Open execution",
        });
      });

    enrichedCandidates
      .filter((candidate) => candidate.lane === "blocked")
      .slice(0, 3)
      .forEach((candidate) => {
        list.push({
          id: `candidate-${candidate.stock_code}`,
          severity: "info",
          title: "Candidate blocked",
          summary: `${candidate.stock_code} blocked: ${candidate.riskReason || candidate.summary}`,
          symbol: candidate.stock_code,
          action: "Inspect candidate",
        });
      });

    return list.slice(0, 8);
  }, [connected, enrichedCandidates, health, killStatus, orders]);

  const pulse = useMemo(() => {
    const activeMovers = movers.filter((item) => Math.abs(toNumber(item.change_pct)) >= 2).length;
    const freshCatalysts = candidates.filter((item) => item.priority >= 60).length;
    const tradeable = enrichedCandidates.filter((item) => item.lane === "eligible").length;
    const blocked = enrichedCandidates.filter((item) => item.lane === "blocked").length;
    const executionIssues = orders.filter((item) => EXECUTION_ISSUE_STATUSES.has(item.status)).length + incidents.filter((item) => item.severity === "critical").length;

    return [
      {
        title: "Active Movers",
        value: activeMovers,
        delta: activeMovers > 0 ? `${activeMovers} above 2% move` : "No significant movers",
        tone: activeMovers > 0 ? "danger" : "neutral",
        onClick: () => setSelectedLane("watching"),
      },
      {
        title: "Fresh Catalysts",
        value: freshCatalysts,
        delta: `${candidates.length} total events scanned`,
        tone: freshCatalysts > 0 ? "info" : "neutral",
        onClick: () => setSelectedLane("watching"),
      },
      {
        title: "Tradeable",
        value: tradeable,
        delta: tradeable > 0 ? "Ready for operator review" : "No eligible candidates",
        tone: tradeable > 0 ? "success" : "neutral",
        onClick: () => setSelectedLane("eligible"),
      },
      {
        title: "Blocked",
        value: blocked,
        delta: blocked > 0 ? "Needs risk or execution review" : "No blocked candidates",
        tone: blocked > 0 ? "warning" : "neutral",
        onClick: () => setSelectedLane("blocked"),
      },
      {
        title: "Execution Issues",
        value: executionIssues,
        delta: executionIssues > 0 ? "Investigate before next trades" : "Execution path stable",
        tone: executionIssues > 0 ? "danger" : "success",
        onClick: () => setSelectedLane("executed"),
      },
    ];
  }, [candidates.length, enrichedCandidates, incidents, movers, orders]);

  const laneCards = useMemo(() => ({
    eligible: enrichedCandidates.filter((item) => item.lane === "eligible"),
    blocked: enrichedCandidates.filter((item) => item.lane === "blocked"),
    watching: enrichedCandidates.filter((item) => item.lane === "watching"),
    executed: enrichedCandidates.filter((item) => item.lane === "executed"),
  }), [enrichedCandidates]);

  const selectedMover = movers.find((item) => item.stock_code === selectedSymbol) || null;
  const selectedCandidate = enrichedCandidates.find((item) => item.stock_code === selectedSymbol) || null;
  const selectedOrders = selectedSymbol ? orders.filter((item) => item.stock_code === selectedSymbol).slice(0, 5) : [];

  useEffect(() => {
    const fallback = enrichedCandidates[0]?.stock_code || movers[0]?.stock_code || null;
    if (!selectedSymbol && fallback) setSelectedSymbol(fallback);
  }, [enrichedCandidates, movers, selectedSymbol]);

  useEffect(() => {
    if (!selectedSymbol) {
      setNewsItems([]);
      return;
    }
    setNewsLoading(true);
    apiGet<NewsItem[]>(`/market/news/${selectedSymbol}?limit=5`)
      .then(setNewsItems)
      .catch(() => setNewsItems([]))
      .finally(() => setNewsLoading(false));
  }, [selectedSymbol]);

  const killActive = killStatus?.kill_switch === "active";
  const lastUpdate = lastTick?.received_at || "";

  return (
    <div className="page-content">
      <section className={`command-strip ${killActive ? "is-danger" : "is-safe"}`}>
        <div className="command-strip-status">
          <StatusBadge label={connected ? "Live" : "Offline"} tone={connected ? "success" : "danger"} />
          <StatusBadge label={killActive ? "Kill Switch Active" : "Trading Enabled"} tone={killActive ? "danger" : "success"} />
          <StatusBadge label={killStatus?.session.allowed ? "Session Open" : "Session Blocked"} tone={killStatus?.session.allowed ? "info" : "warning"} />
          <StatusBadge label={health?.status === "ok" ? "API Healthy" : "API Degraded"} tone={health?.status === "ok" ? "success" : "danger"} />
          <StatusBadge label={health?.db === "ok" ? "DB OK" : "DB Issue"} tone={health?.db === "ok" ? "neutral" : "danger"} />
          <StatusBadge label={health?.redis === "ok" ? "Redis OK" : "Redis Issue"} tone={health?.redis === "ok" ? "neutral" : "danger"} />
        </div>
        <div className="command-strip-meta">
          <span>Daily P&amp;L {formatSigned(killStatus?.daily_loss_pct ?? 0)}%</span>
          <span>Broker Fails {killStatus?.broker_failures ?? 0}/{killStatus?.broker_limit ?? 3}</span>
          <span>Last Tick {lastUpdate ? formatTime(lastUpdate) : "-"}</span>
        </div>
        <div className="command-strip-actions">
          <button className="btn btn-sm btn-primary" onClick={() => { void loadData(); void runEventScan(); }} disabled={scanning}>
            {scanning ? "Scanning..." : "Scan Now"}
          </button>
          {!killActive ? (
            <button
              className="btn btn-sm command-strip-kill"
              onClick={() => {
                if (confirm("Kill switch 활성화?")) {
                  apiPost("/trading/kill-switch/activate").then(() => void loadData());
                }
              }}
            >
              Kill Switch
            </button>
          ) : (
            <button className="btn btn-sm command-strip-resume" onClick={() => apiPost("/trading/kill-switch/deactivate").then(() => void loadData())}>
              Resume
            </button>
          )}
        </div>
      </section>

      <section className="command-pulse-grid">
        {pulse.map((item) => (
          <button key={item.title} className={`command-pulse-card tone-${item.tone}`} onClick={item.onClick}>
            <span className="command-pulse-title">{item.title}</span>
            <span className="command-pulse-value">{item.value}</span>
            <span className="command-pulse-delta">{item.delta}</span>
          </button>
        ))}
      </section>

      <section className="command-main-grid">
        <div className="card command-panel">
          <div className="command-panel-header">
            <div>
              <h3 className="card-title">Priority Movers</h3>
              <p className="command-panel-subtitle">Ranked by move intensity from the live cache.</p>
            </div>
            <span className="text-secondary">{movers.length} tracked</span>
          </div>
          <div className="command-list">
            {movers.length === 0 && <div className="command-empty">No live movers available.</div>}
            {movers.map((item, index) => {
              const matchedCandidate = enrichedCandidates.find((candidate) => candidate.stock_code === item.stock_code);
              return (
                <button
                  key={item.stock_code}
                  className={`command-row ${selectedSymbol === item.stock_code ? "is-selected" : ""}`}
                  onClick={() => setSelectedSymbol(item.stock_code)}
                >
                  <div className="command-row-rank">{index + 1}</div>
                  <div className="command-row-main">
                    <div className="command-row-title">
                      <span className="font-bold">{item.stock_name || item.stock_code}</span>
                      <span className="text-secondary">{item.stock_code}</span>
                    </div>
                    <div className="command-row-meta">
                      <span>{item.sector || "Unclassified"}</span>
                      <span>Vol {formatCompact(toNumber(item.volume))}</span>
                      {item.stale && <span className="text-warning">stale</span>}
                    </div>
                  </div>
                  <div className="command-row-change">
                    <span className={toNumber(item.change_pct) >= 0 ? "text-up font-heavy" : "text-down font-heavy"}>
                      {formatSigned(toNumber(item.change_pct))}%
                    </span>
                    <span className="text-secondary">{formatNumber(toNumber(item.price))}</span>
                  </div>
                  <div className="command-row-badges">
                    {matchedCandidate ? <Badge tone="info" label={EVENT_LABELS[matchedCandidate.event_type] || matchedCandidate.event_type} /> : <Badge tone="neutral" label="No catalyst" />}
                    {matchedCandidate ? <Badge tone={toneForLane(matchedCandidate.lane)} label={LANE_TITLES[matchedCandidate.lane]} /> : <Badge tone="neutral" label="Watching" />}
                    {matchedCandidate?.recentOrder ? <Badge tone={toneForOrder(matchedCandidate.recentOrder.status)} label={matchedCandidate.recentOrder.status} /> : null}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="card command-panel">
          <div className="command-panel-header">
            <div>
              <h3 className="card-title">Incident Queue</h3>
              <p className="command-panel-subtitle">System, risk, and execution items that need attention.</p>
            </div>
            <span className="text-secondary">{incidents.length} open</span>
          </div>
          <div className="command-list">
            {incidents.length === 0 && <div className="command-empty">No active incidents.</div>}
            {incidents.map((incident) => (
              <div key={incident.id} className={`incident-card severity-${incident.severity}`}>
                <div className="incident-card-header">
                  <Badge tone={incident.severity === "critical" ? "danger" : incident.severity === "warning" ? "warning" : "info"} label={incident.severity.toUpperCase()} />
                  {incident.symbol ? <span className="text-secondary">{incident.symbol}</span> : null}
                </div>
                <div className="incident-card-title">{incident.title}</div>
                <div className="incident-card-summary">{incident.summary}</div>
                <div className="incident-card-action">{incident.action}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card command-panel">
        <div className="command-panel-header">
          <div>
            <h3 className="card-title">Candidate Lanes</h3>
            <p className="command-panel-subtitle">Engine intent grouped by actionability and execution state.</p>
          </div>
          <div className="command-lane-tabs">
            {(Object.keys(LANE_TITLES) as CandidateLane[]).map((lane) => (
              <button
                key={lane}
                className={`command-lane-tab ${selectedLane === lane ? "is-active" : ""}`}
                onClick={() => setSelectedLane(lane)}
              >
                {LANE_TITLES[lane]} ({laneCards[lane].length})
              </button>
            ))}
          </div>
        </div>
        <div className="candidate-grid">
          {laneCards[selectedLane].length === 0 && <div className="command-empty">No candidates in this lane.</div>}
          {laneCards[selectedLane].map((candidate) => (
            <button
              key={`${candidate.stock_code}-${candidate.event_type}`}
              className={`candidate-card ${selectedSymbol === candidate.stock_code ? "is-selected" : ""}`}
              onClick={() => setSelectedSymbol(candidate.stock_code)}
            >
              <div className="candidate-card-header">
                <div>
                  <div className="candidate-card-title">{candidate.stock_name || candidate.stock_code}</div>
                  <div className="candidate-card-subtitle">{candidate.stock_code} · {candidate.priority.toFixed(0)} priority</div>
                </div>
                <Badge tone={toneForLane(candidate.lane)} label={LANE_TITLES[candidate.lane]} />
              </div>
              <div className="candidate-card-body">
                <Badge tone="info" label={EVENT_LABELS[candidate.event_type] || candidate.event_type} />
                <span>{candidate.summary}</span>
              </div>
              <div className="candidate-card-footer">
                <span>{candidate.riskReason || "No active risk block"}</span>
                {candidate.recentOrder ? <span>Order {candidate.recentOrder.status}</span> : <span>No recent order</span>}
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="card command-panel">
        <div className="command-panel-header">
          <div>
            <h3 className="card-title">Selected Detail</h3>
            <p className="command-panel-subtitle">Catalysts, execution state, and recent news for the selected symbol.</p>
          </div>
          <span className="text-secondary">{selectedSymbol || "No symbol selected"}</span>
        </div>
        {!selectedSymbol && <div className="command-empty">Select a mover or candidate to inspect details.</div>}
        {selectedSymbol && (
          <div className="detail-grid">
            <div className="detail-card">
              <div className="detail-card-label">Price</div>
              <div className="detail-card-value">{selectedMover ? formatNumber(toNumber(selectedMover.price)) : "-"}</div>
              <div className={selectedMover && toNumber(selectedMover.change_pct) >= 0 ? "text-up font-heavy" : "text-down font-heavy"}>
                {selectedMover ? `${formatSigned(toNumber(selectedMover.change_pct))}%` : "No move data"}
              </div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">Catalyst</div>
              <div className="detail-card-value detail-small">{selectedCandidate ? (EVENT_LABELS[selectedCandidate.event_type] || selectedCandidate.event_type) : "No candidate"}</div>
              <div className="text-secondary">{selectedCandidate?.summary || "No catalyst summary available"}</div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">Risk</div>
              <div className="detail-card-value detail-small">{selectedCandidate?.riskReason || "No active block"}</div>
              <div className="text-secondary">
                Session {killStatus?.session.allowed ? "open" : "blocked"} · Broker fails {killStatus?.broker_failures ?? 0}
              </div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">Execution</div>
              <div className="detail-card-value detail-small">{selectedCandidate?.recentOrder?.status || "No recent order"}</div>
              <div className="text-secondary">
                {selectedCandidate?.recentOrder ? `${selectedCandidate.recentOrder.filled_qty}/${selectedCandidate.recentOrder.quantity} filled` : "Waiting for action"}
              </div>
            </div>
            <div className="detail-panel">
              <div className="detail-panel-title">Recent Order Timeline</div>
              {selectedOrders.length === 0 && <div className="command-empty small">No recent orders for this symbol.</div>}
              {selectedOrders.length > 0 && (
                <div className="timeline-list">
                  {selectedOrders.map((order) => (
                    <div key={order.order_id} className="timeline-item">
                      <div className="timeline-top">
                        <Badge tone={toneForOrder(order.status)} label={order.status} />
                        <span className="text-secondary">{formatTime(order.time)}</span>
                      </div>
                      <div className="timeline-main">
                        {order.side} {order.quantity} · filled {order.filled_qty}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="detail-panel">
              <div className="detail-panel-title">Latest News</div>
              {newsLoading && <div className="command-empty small">Loading news...</div>}
              {!newsLoading && newsItems.length === 0 && <div className="command-empty small">No recent news.</div>}
              {!newsLoading && newsItems.length > 0 && (
                <div className="news-stack">
                  {newsItems.map((item, index) => (
                    <a key={`${item.time}-${index}`} className="news-compact" href={item.url} target="_blank" rel="noreferrer">
                      <div className="news-compact-title">{item.title}</div>
                      <div className="news-compact-meta">{item.source} · {formatTime(item.time)}</div>
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function toNumber(value: number | string | undefined) {
  return typeof value === "number" ? value : Number(value || 0);
}

function formatSigned(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function formatNumber(value: number) {
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

function formatCompact(value: number) {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return `${value}`;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("ko-KR");
}

function summarizeDetails(details: Record<string, unknown>) {
  const entries = Object.entries(details).slice(0, 3).map(([key, value]) => `${key}: ${String(value)}`);
  return entries.length > 0 ? entries.join(" · ") : "No details";
}

function toneForLane(lane: CandidateLane): BadgeTone {
  if (lane === "eligible") return "success";
  if (lane === "blocked") return "warning";
  if (lane === "executed") return "info";
  return "neutral";
}

function toneForOrder(status: string): BadgeTone {
  if (status === "FILLED") return "success";
  if (EXECUTION_ISSUE_STATUSES.has(status)) return "danger";
  if (EXECUTION_ACTIVE_STATUSES.has(status)) return "info";
  return "neutral";
}

type BadgeTone = "success" | "danger" | "warning" | "info" | "neutral";

function Badge({ label, tone }: { label: string; tone: BadgeTone }) {
  return <span className={`command-badge tone-${tone}`}>{label}</span>;
}

function StatusBadge({ label, tone }: { label: string; tone: BadgeTone }) {
  return <span className={`command-status-badge tone-${tone}`}>{label}</span>;
}
