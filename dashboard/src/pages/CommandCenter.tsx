import { useEffect, useMemo, useState } from "react";
import DirectionValue from "../components/DirectionValue";
import { apiGet, apiPost } from "../hooks/useApi";
import { useWebSocket } from "../hooks/useWebSocket";
import { eventTypeLabel, orderStatusLabel } from "../lib/labels";
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

interface MarketIndex {
  name: string;
  price: number;
  change: number;
  change_pct: number;
  open: number;
  high: number;
  low: number;
  updated_at: string | null;
  error?: string;
}

const EXECUTION_ISSUE_STATUSES = new Set(["REJECTED", "BLOCKED", "FAILED", "UNKNOWN"]);
const EXECUTION_ACTIVE_STATUSES = new Set(["SUBMITTED", "ACKED", "PARTIALLY_FILLED", "FILLED"]);

export default function CommandCenterPage({ t: _t }: { t: (k: string) => string }) {
  const [movers, setMovers] = useState<Mover[]>([]);
  const [candidates, setCandidates] = useState<EventCandidate[]>([]);
  const [killStatus, setKillStatus] = useState<KillSwitchStatus | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [marketIndexes, setMarketIndexes] = useState<MarketIndex[]>([]);
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [selectedLane, setSelectedLane] = useState<CandidateLane>("eligible");
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [scanning, setScanning] = useState(false);

  const openAsset = (code: string) => {
    window.location.hash = `asset/${code}`;
  };

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
      const [moversData, ksData, healthData, orderData, indexData] = await Promise.all([
        apiGet<{ movers: Mover[] }>("/market/movers?limit=20"),
        apiGet<KillSwitchStatus>("/trading/kill-switch/status"),
        apiGet<HealthStatus>("/health"),
        apiGet<OrderHistoryItem[]>("/order/history?limit=50"),
        apiGet<{ indexes: MarketIndex[] }>("/index/realtime"),
      ]);
      setMovers(moversData.movers || []);
      setKillStatus(ksData);
      setHealth(healthData);
      setOrders(orderData || []);
      setMarketIndexes(indexData.indexes || []);
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
          riskReason = _t("state.killActive");
        } else if (sessionBlocked) {
          lane = "blocked";
          riskReason = killStatus?.session.message || _t("state.sessionBlocked");
        } else if (brokerBlocked) {
          lane = "blocked";
          riskReason = _t("sys.brokerFails");
        } else if (candidate.priority >= 75) {
          lane = "eligible";
        } else {
          lane = "watching";
        }

        if (recentOrder && EXECUTION_ISSUE_STATUSES.has(recentOrder.status)) {
          lane = "blocked";
          riskReason = `${_t("command.executionIssues")}: ${recentOrder.status}`;
        }

        return { ...candidate, lane, summary, recentOrder, riskReason };
      })
      .sort((a, b) => b.priority - a.priority);
  }, [_t, candidates, killStatus, orders]);

  const incidents = useMemo<IncidentItem[]>(() => {
    const list: IncidentItem[] = [];

    if (!connected) {
      list.push({
        id: "ws-offline",
        severity: "critical",
        title: _t("state.offline"),
        summary: `${_t("nav.command")} WebSocket disconnected. ${_t("state.live")} state may be ${_t("market.stale")}.`,
        action: _t("exec.refresh"),
      });
    }

    if (health && health.status !== "ok") {
      list.push({
        id: "api-health",
        severity: "critical",
        title: _t("state.apiDegraded"),
        summary: `API=${health.status} DB=${health.db} Redis=${health.redis}`,
        action: _t("dash.systemStatus"),
      });
    }

    if (killStatus?.kill_switch === "active") {
      list.push({
        id: "kill-switch",
        severity: "critical",
        title: _t("state.killActive"),
        summary: _t("state.blocked"),
        action: _t("command.blocked"),
      });
    }

    if (killStatus && !killStatus.session.allowed) {
      list.push({
        id: "session-block",
        severity: "warning",
        title: _t("state.sessionBlocked"),
        summary: killStatus.session.message || _t("state.sessionBlocked"),
        action: _t("command.risk"),
      });
    }

    if ((killStatus?.broker_failures ?? 0) > 0) {
      list.push({
        id: "broker-failures",
        severity: (killStatus?.broker_failures ?? 0) >= (killStatus?.broker_limit ?? 3) ? "critical" : "warning",
        title: _t("sys.brokerFails"),
        summary: `${killStatus?.broker_failures ?? 0}/${killStatus?.broker_limit ?? 3} recent failures recorded.`,
        action: _t("exec.eodReconcile"),
      });
    }

    orders
      .filter((order) => EXECUTION_ISSUE_STATUSES.has(order.status))
      .slice(0, 4)
      .forEach((order) => {
        list.push({
          id: `order-${order.order_id}`,
          severity: "warning",
          title: `${_t("command.orderStatus")} ${order.status}`,
          summary: `${order.stock_code} ${order.side} ${order.filled_qty}/${order.quantity}`,
          symbol: order.stock_code,
          action: _t("command.execution"),
        });
      });

    enrichedCandidates
      .filter((candidate) => candidate.lane === "blocked")
      .slice(0, 3)
      .forEach((candidate) => {
        list.push({
          id: `candidate-${candidate.stock_code}`,
          severity: "info",
          title: _t("state.blocked"),
          summary: `${candidate.stock_code} blocked: ${candidate.riskReason || candidate.summary}`,
          symbol: candidate.stock_code,
          action: _t("state.watching"),
        });
      });

    return list.slice(0, 8);
  }, [_t, connected, enrichedCandidates, health, killStatus, orders]);

  const pulse = useMemo(() => {
    const activeMovers = movers.filter((item) => Math.abs(toNumber(item.change_pct)) >= 2).length;
    const freshCatalysts = candidates.filter((item) => item.priority >= 60).length;
    const tradeable = enrichedCandidates.filter((item) => item.lane === "eligible").length;
    const blocked = enrichedCandidates.filter((item) => item.lane === "blocked").length;
    const executionIssues = orders.filter((item) => EXECUTION_ISSUE_STATUSES.has(item.status)).length + incidents.filter((item) => item.severity === "critical").length;

    return [
      {
        title: _t("command.activeMovers"),
        value: activeMovers,
        delta: activeMovers > 0 ? `${activeMovers} above 2% move` : _t("command.noLiveMovers"),
        tone: activeMovers > 0 ? "danger" : "neutral",
        onClick: () => setSelectedLane("watching"),
      },
      {
        title: _t("command.freshCatalysts"),
        value: freshCatalysts,
        delta: `${candidates.length} total events scanned`,
        tone: freshCatalysts > 0 ? "info" : "neutral",
        onClick: () => setSelectedLane("watching"),
      },
      {
        title: _t("command.tradeable"),
        value: tradeable,
        delta: tradeable > 0 ? _t("state.eligible") : _t("command.noCandidatesLane"),
        tone: tradeable > 0 ? "success" : "neutral",
        onClick: () => setSelectedLane("eligible"),
      },
      {
        title: _t("command.blocked"),
        value: blocked,
        delta: blocked > 0 ? _t("command.risk") : _t("command.noCandidatesLane"),
        tone: blocked > 0 ? "warning" : "neutral",
        onClick: () => setSelectedLane("blocked"),
      },
      {
        title: _t("command.executionIssues"),
        value: executionIssues,
        delta: executionIssues > 0 ? _t("command.execution") : _t("command.execution"),
        tone: executionIssues > 0 ? "danger" : "success",
        onClick: () => setSelectedLane("executed"),
      },
    ];
  }, [_t, candidates.length, enrichedCandidates, incidents, movers, orders]);

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

  const [tradingMode, setTradingMode] = useState<string>("paper");
  const [modeChanging, setModeChanging] = useState(false);

  useEffect(() => {
    apiGet<{ mode: string }>("/trading/mode").then((d) => setTradingMode(d.mode)).catch(() => {});
  }, []);

  const toggleTradingMode = async () => {
    const targetMode = tradingMode === "paper" ? "live" : "paper";
    if (targetMode === "live") {
      const msg = _t("command.confirmLive");
      if (!confirm(msg)) return;
      // Must activate kill switch first
      const ks = await apiGet<KillSwitchStatus>("/trading/kill-switch/status");
      if (ks.kill_switch !== "active") {
        alert(_t("command.killFirstForLive"));
        return;
      }
    }
    setModeChanging(true);
    try {
      const resp = await apiPost<{ status: string; mode: string }>("/trading/mode", {
        mode: targetMode,
        confirm: targetMode === "live" ? true : undefined,
      });
      if (resp.mode) setTradingMode(resp.mode);
      else if (resp.status === "unchanged") { /* no-op */ }
      else alert(JSON.stringify(resp));
      void loadData();
    } catch (e) {
      alert(String(e));
    }
    setModeChanging(false);
  };

  const killActive = killStatus?.kill_switch === "active";
  const lastUpdate = lastTick?.received_at || "";
  const isLive = tradingMode === "live";

  return (
    <div className="page-content">
      <section className={`command-strip ${isLive ? "is-live" : killActive ? "is-danger" : "is-safe"}`} style={{ position: "relative" }}>
        <div className="command-strip-status">
          <StatusBadge label={connected ? _t("state.live") : _t("state.offline")} tone={connected ? "success" : "danger"} />
          <StatusBadge label={isLive ? _t("state.liveMode") : _t("state.paperMode")} tone={isLive ? "danger" : "info"} />
          <StatusBadge label={killActive ? _t("state.killActive") : _t("state.enabled")} tone={killActive ? "danger" : "success"} />
          <StatusBadge label={killStatus?.session.allowed ? _t("state.sessionOpen") : _t("state.sessionBlocked")} tone={killStatus?.session.allowed ? "info" : "warning"} />
          <StatusBadge label={health?.status === "ok" ? _t("state.apiHealthy") : _t("state.apiDegraded")} tone={health?.status === "ok" ? "success" : "danger"} />
          <StatusBadge label={health?.db === "ok" ? _t("state.dbOk") : _t("state.dbIssue")} tone={health?.db === "ok" ? "neutral" : "danger"} />
          <StatusBadge label={health?.redis === "ok" ? _t("state.redisOk") : _t("state.redisIssue")} tone={health?.redis === "ok" ? "neutral" : "danger"} />
        </div>
        <div className="command-strip-meta">
          <span>{_t("sys.dailyPnl")} {formatSigned(killStatus?.daily_loss_pct ?? 0)}%</span>
          <span>{_t("sys.brokerFails")} {killStatus?.broker_failures ?? 0}/{killStatus?.broker_limit ?? 3}</span>
          <span>{_t("sys.lastTick")} {lastUpdate ? formatTime(lastUpdate) : "-"}</span>
        </div>
        <div className="command-strip-actions">
          <button className="btn btn-sm btn-primary" onClick={() => { void loadData(); void runEventScan(); }} disabled={scanning}>
            {scanning ? _t("command.scanning") : _t("command.scanNow")}
          </button>
          {!killActive ? (
            <button
              className="btn btn-sm command-strip-kill"
              onClick={() => {
                if (confirm(_t("command.confirmKill"))) {
                  apiPost("/trading/kill-switch/activate").then(() => void loadData());
                }
              }}
            >
              {_t("command.killSwitch")}
            </button>
          ) : (
            <button className="btn btn-sm command-strip-resume" onClick={() => apiPost("/trading/kill-switch/deactivate").then(() => void loadData())}>
              {_t("command.resume")}
            </button>
          )}
          <button
            className={`btn btn-sm ${isLive ? "command-mode-live" : "command-mode-paper"}`}
            onClick={toggleTradingMode}
            disabled={modeChanging}
          >
            {modeChanging ? "..." : isLive ? _t("command.switchToPaper") : _t("command.switchToLive")}
          </button>
        </div>
      </section>

      <section className="command-index-grid">
        {marketIndexes.map((item) => (
          <div key={item.name} className="card command-index-card">
            <div className="command-index-top">
              <span className="command-index-name">{item.name}</span>
              <span className="text-secondary">{item.updated_at ? formatTime(item.updated_at) : "-"}</span>
            </div>
            <div className="command-index-price">{formatNumber(item.price)}</div>
            <div className="command-index-change">
              <DirectionValue value={item.change} precision={2} />
              <DirectionValue value={item.change_pct} suffix="%" />
            </div>
            <div className="command-index-meta">
              <span>{_t("command.indexOpen")} {formatNumber(item.open)}</span>
              <span>{_t("command.indexHigh")} {formatNumber(item.high)}</span>
              <span>{_t("command.indexLow")} {formatNumber(item.low)}</span>
            </div>
          </div>
        ))}
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
              <h3 className="card-title">{_t("command.priorityMovers")}</h3>
              <p className="command-panel-subtitle">{_t("command.priorityMoversSub")}</p>
            </div>
            <span className="text-secondary">{movers.length} {_t("command.tracked")}</span>
          </div>
          <div className="command-list">
            {movers.length === 0 && <div className="command-empty">{_t("command.noLiveMovers")}</div>}
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
                      <button className="link-button font-bold" onClick={(e) => { e.stopPropagation(); openAsset(item.stock_code); }}>{item.stock_name || item.stock_code}</button>
                      <span className="text-secondary">{item.stock_code}</span>
                    </div>
                    <div className="command-row-meta">
                      <span>{item.sector || _t("state.unclassified")}</span>
                      <span>Vol {formatCompact(toNumber(item.volume))}</span>
                      {item.stale && <span className="text-warning">{_t("market.stale")}</span>}
                    </div>
                  </div>
                  <div className="command-row-change">
                    <DirectionValue value={toNumber(item.change_pct)} suffix="%" />
                    <span className="text-secondary">{formatNumber(toNumber(item.price))}</span>
                  </div>
                  <div className="command-row-badges">
                    {matchedCandidate ? <Badge tone="info" label={eventTypeLabel(matchedCandidate.event_type, _t)} /> : <Badge tone="neutral" label={_t("state.noCatalyst")} />}
                    {matchedCandidate ? <Badge tone={toneForLane(matchedCandidate.lane)} label={_t(`state.${matchedCandidate.lane}`)} /> : <Badge tone="neutral" label={_t("state.watching")} />}
                    {matchedCandidate?.recentOrder ? <Badge tone={toneForOrder(matchedCandidate.recentOrder.status)} label={orderStatusLabel(matchedCandidate.recentOrder.status, _t)} /> : null}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="card command-panel">
          <div className="command-panel-header">
            <div>
              <h3 className="card-title">{_t("command.incidentQueue")}</h3>
              <p className="command-panel-subtitle">{_t("command.incidentQueueSub")}</p>
            </div>
            <span className="text-secondary">{incidents.length} open</span>
          </div>
          <div className="command-list">
            {incidents.length === 0 && <div className="command-empty">{_t("command.noIncidents")}</div>}
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
            <h3 className="card-title">{_t("command.candidateLanes")}</h3>
            <p className="command-panel-subtitle">{_t("command.candidateLanesSub")}</p>
          </div>
          <div className="command-lane-tabs">
            {(["eligible", "blocked", "watching", "executed"] as CandidateLane[]).map((lane) => (
              <button
                key={lane}
                className={`command-lane-tab ${selectedLane === lane ? "is-active" : ""}`}
                onClick={() => setSelectedLane(lane)}
              >
                {_t(`state.${lane}`)} ({laneCards[lane].length})
              </button>
            ))}
          </div>
        </div>
        <div className="candidate-grid">
          {laneCards[selectedLane].length === 0 && <div className="command-empty">{_t("command.noCandidatesLane")}</div>}
          {laneCards[selectedLane].map((candidate) => (
            <button
              key={`${candidate.stock_code}-${candidate.event_type}`}
              className={`candidate-card ${selectedSymbol === candidate.stock_code ? "is-selected" : ""}`}
              onClick={() => setSelectedSymbol(candidate.stock_code)}
            >
              <div className="candidate-card-header">
                <div>
                  <div className="candidate-card-title"><button className="link-button font-bold" onClick={(e) => { e.stopPropagation(); openAsset(candidate.stock_code); }}>{candidate.stock_name || candidate.stock_code}</button></div>
                  <div className="candidate-card-subtitle">{candidate.stock_code} · {candidate.priority.toFixed(0)} {_t("command.priority")}</div>
                </div>
                <Badge tone={toneForLane(candidate.lane)} label={_t(`state.${candidate.lane}`)} />
              </div>
              <div className="candidate-card-body">
                <Badge tone="info" label={eventTypeLabel(candidate.event_type, _t)} />
                <span>{candidate.summary}</span>
              </div>
              <div className="candidate-card-footer">
                <span>{candidate.riskReason || _t("state.noActiveRiskBlock")}</span>
                {candidate.recentOrder ? <span>{_t("command.orderStatus")} {orderStatusLabel(candidate.recentOrder.status, _t)}</span> : <span>{_t("state.noRecentOrder")}</span>}
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="card command-panel">
        <div className="command-panel-header">
          <div>
            <h3 className="card-title">{_t("command.selectedDetail")}</h3>
            <p className="command-panel-subtitle">{_t("command.selectedDetailSub")}</p>
          </div>
          <span className="text-secondary">{selectedSymbol || _t("command.noSymbolSelected")}</span>
        </div>
        {!selectedSymbol && <div className="command-empty">{_t("command.selectToInspect")}</div>}
        {selectedSymbol && (
          <div className="detail-grid">
            <div className="detail-card">
              <div className="detail-card-label">{_t("command.price")}</div>
              <div className="detail-card-value">{selectedMover ? formatNumber(toNumber(selectedMover.price)) : "-"}</div>
              <div>{selectedMover ? <DirectionValue value={toNumber(selectedMover.change_pct)} suffix="%" /> : "-"}</div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">{_t("command.catalyst")}</div>
              <div className="detail-card-value detail-small">{selectedCandidate ? eventTypeLabel(selectedCandidate.event_type, _t) : _t("state.noCandidate")}</div>
              <div className="text-secondary">{selectedCandidate?.summary || _t("state.noCatalystSummary")}</div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">{_t("command.risk")}</div>
              <div className="detail-card-value detail-small">{selectedCandidate?.riskReason || _t("state.noActiveRiskBlock")}</div>
              <div className="text-secondary">
                {_t("state.sessionOpen")} {killStatus?.session.allowed ? _t("state.enabled") : _t("state.blocked")} · {_t("sys.brokerFails")} {killStatus?.broker_failures ?? 0}
              </div>
            </div>
            <div className="detail-card">
              <div className="detail-card-label">{_t("command.execution")}</div>
              <div className="detail-card-value detail-small">{selectedCandidate?.recentOrder ? orderStatusLabel(selectedCandidate.recentOrder.status, _t) : _t("state.noRecentOrder")}</div>
              <div className="text-secondary">
                {selectedCandidate?.recentOrder ? `${selectedCandidate.recentOrder.filled_qty}/${selectedCandidate.recentOrder.quantity} ${_t("exec.filled")}` : _t("state.waitingAction")}
              </div>
            </div>
            <div className="detail-panel">
              <div className="detail-panel-title">{_t("command.recentOrderTimeline")}</div>
              {selectedOrders.length === 0 && <div className="command-empty small">{_t("command.noRecentOrdersSymbol")}</div>}
              {selectedOrders.length > 0 && (
                <div className="timeline-list">
                  {selectedOrders.map((order) => (
                    <div key={order.order_id} className="timeline-item">
                      <div className="timeline-top">
                        <Badge tone={toneForOrder(order.status)} label={orderStatusLabel(order.status, _t)} />
                        <span className="text-secondary">{formatTime(order.time)}</span>
                      </div>
                      <div className="timeline-main">
                        {_t(order.side === "BUY" ? "signal.buy" : "signal.sell")} {order.quantity} · {_t("exec.filled")} {order.filled_qty}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="detail-panel">
              <div className="detail-panel-title">{_t("command.latestNews")}</div>
              {newsLoading && <div className="command-empty small">{_t("command.loadingNews")}</div>}
              {!newsLoading && newsItems.length === 0 && <div className="command-empty small">{_t("command.noRecentNews")}</div>}
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
