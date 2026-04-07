import { useEffect, useMemo, useState } from "react";
import DirectionValue from "../components/DirectionValue";
import { LightweightChart } from "../components/charts";
import { apiGet, apiPost } from "../hooks/useApi";
import { useWebSocket } from "../hooks/useWebSocket";
import { toNum, formatSigned, formatNumber, formatCompact, formatDateTime, summarizeDetails } from "../lib/formatting";
import { eventTypeLabel, orderStatusLabel } from "../lib/labels";
import { EXECUTION_ISSUE_STATUSES, EXECUTION_ACTIVE_STATUSES, toneForLane, toneForOrder } from "../lib/statusMapping";
import type { HealthStatus, OrderHistoryItem, Mover, EventCandidate, KillSwitchStatus, NewsItem, MarketIndex } from "../types";

import type { CandidateLane } from "../lib/statusMapping";

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

interface IndexChartResponse {
  name: string;
  range: string;
  points: Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
  updated_at: string;
}

// MarketIndex imported from types.ts

// Status constants imported from lib/statusMapping.ts

export default function CommandCenterPage({ t: _t }: { t: (k: string) => string }) {
  const [movers, setMovers] = useState<Mover[]>([]);
  const [candidates, setCandidates] = useState<EventCandidate[]>([]);
  const [killStatus, setKillStatus] = useState<KillSwitchStatus | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [marketIndexes, setMarketIndexes] = useState<MarketIndex[]>([]);
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<string | null>(null);
  const [indexRange, setIndexRange] = useState<"1M" | "3M" | "1Y" | "MAX">("3M");
  const [indexChart, setIndexChart] = useState<IndexChartResponse | null>(null);
  const [indexChartLoading, setIndexChartLoading] = useState(false);
  const [selectedLane, setSelectedLane] = useState<CandidateLane>("eligible");
  const [latestNews, setLatestNews] = useState<NewsItem[]>([]);
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [killModalOpen, setKillModalOpen] = useState(false);
  const [killReason, setKillReason] = useState("");
  const activeIndex = selectedIndex ?? marketIndexes[0]?.name ?? null;

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
          .sort((a, b) => Math.abs(toNum(b.change_pct)) - Math.abs(toNum(a.change_pct)))
          .slice(0, 20);
      });
    },
  });

  const loadData = async () => {
    try {
      const [moversData, ksData, healthData, orderData, indexData, newsData] = await Promise.all([
        apiGet<{ movers: Mover[] }>("/market/movers?limit=20"),
        apiGet<KillSwitchStatus>("/trading/kill-switch/status"),
        apiGet<HealthStatus>("/health"),
        apiGet<OrderHistoryItem[]>("/order/history?limit=50"),
        apiGet<{ indexes: MarketIndex[] }>("/index/realtime"),
        apiGet<NewsItem[]>("/market/news/all?limit=15"),
      ]);
      setMovers(moversData.movers || []);
      setKillStatus(ksData);
      setHealth(healthData);
      setOrders(orderData || []);
      setMarketIndexes(indexData.indexes || []);
      setLatestNews(newsData || []);
    } catch {
      // keep previous state on transient failures
    }
  };

  useEffect(() => {
    if (!activeIndex) return;
    let cancelled = false;
    setIndexChartLoading(true);
    apiGet<IndexChartResponse>(`/index/chart?name=${encodeURIComponent(activeIndex)}&range=${indexRange}`)
      .then((data) => {
        if (!cancelled) setIndexChart(data);
      })
      .catch(() => {
        if (!cancelled) setIndexChart(null);
      })
      .finally(() => {
        if (!cancelled) setIndexChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeIndex, indexRange]);

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
    const activeMovers = movers.filter((item) => Math.abs(toNum(item.change_pct)) >= 2).length;
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
        onClick: () => { window.location.hash = "monitor/movers"; },
      },
      {
        title: _t("command.freshCatalysts"),
        value: freshCatalysts,
        delta: `${candidates.length} total events scanned`,
        tone: freshCatalysts > 0 ? "info" : "neutral",
        onClick: () => { window.location.hash = "monitor/catalysts"; },
      },
      {
        title: _t("command.tradeable"),
        value: tradeable,
        delta: tradeable > 0 ? _t("state.eligible") : _t("command.noCandidatesLane"),
        tone: tradeable > 0 ? "success" : "neutral",
        onClick: () => { window.location.hash = "monitor/tradeable"; },
      },
      {
        title: _t("command.blocked"),
        value: blocked,
        delta: blocked > 0 ? _t("command.risk") : _t("command.noCandidatesLane"),
        tone: blocked > 0 ? "warning" : "neutral",
        onClick: () => { window.location.hash = "monitor/blocked"; },
      },
      {
        title: _t("command.executionIssues"),
        value: executionIssues,
        delta: executionIssues > 0 ? _t("command.execution") : _t("command.execution"),
        tone: executionIssues > 0 ? "danger" : "success",
        onClick: () => { window.location.hash = "monitor/issues"; },
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
          <span>{_t("sys.lastTick")} {lastUpdate ? formatDateTime(lastUpdate) : "-"}</span>
        </div>
        <div className="command-strip-actions">
          <button className="btn btn-sm btn-primary" onClick={() => { void loadData(); void runEventScan(); }} disabled={scanning}>
            {scanning ? _t("command.scanning") : _t("command.scanNow")}
          </button>
          {!killActive ? (
            <button
              className="btn btn-sm command-strip-kill"
              onClick={() => setKillModalOpen(true)}
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

      <nav className="command-jump-bar">
        {[
          { id: "cmd-indexes", label: _t("command.jumpIndexes") },
          { id: "cmd-news", label: _t("command.jumpNews") },
          { id: "cmd-pulse", label: _t("command.jumpPulse") },
          { id: "cmd-movers", label: _t("command.jumpMovers") },
          { id: "cmd-candidates", label: _t("command.jumpCandidates") },
          { id: "cmd-detail", label: _t("command.jumpDetail") },
        ].map((tab) => (
          <button key={tab.id} className="command-jump-btn" onClick={() => document.getElementById(tab.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            {tab.label}
          </button>
        ))}
      </nav>

      <section id="cmd-indexes" className="command-index-grid">
        {marketIndexes.map((item) => (
          <button
            key={item.name}
            type="button"
            className={`card command-index-card ${activeIndex === item.name ? "is-selected" : ""}`}
            onClick={() => setSelectedIndex(item.name)}
          >
            <div className="command-index-top">
              <span className="command-index-name">{item.name}</span>
              <span className="text-secondary">{item.updated_at ? formatDateTime(item.updated_at) : "-"}</span>
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
          </button>
        ))}
      </section>

      {activeIndex && (
        <section className="card command-panel command-index-chart-card">
          <div className="command-panel-header">
            <div>
              <h3 className="card-title">{activeIndex} 차트</h3>
              <p className="command-panel-subtitle">
                커맨드 센터에서 선택한 지수의 최근 흐름입니다.
                {" "}
                <strong>{indexRange}</strong>
                {indexChart?.points?.length ? ` · ${indexChart.points.length}개 포인트` : ""}
              </p>
            </div>
            <div className="flex gap-sm items-center" style={{ flexWrap: "wrap" }}>
              {(["1M", "3M", "1Y", "MAX"] as const).map((rangeKey) => (
                <button
                  key={rangeKey}
                  type="button"
                  className={`btn btn-sm ${indexRange === rangeKey ? "btn-primary" : ""}`}
                  onClick={() => setIndexRange(rangeKey)}
                >
                  {rangeKey}
                </button>
              ))}
            </div>
          </div>
          {indexChartLoading ? (
            <div className="command-empty">지수 차트를 불러오는 중...</div>
          ) : indexChart?.points?.length ? (
            <LightweightChart
              data={indexChart.points}
              mode="line"
              volume={false}
              height={280}
              showMA20={false}
              showMA50={false}
            />
          ) : (
            <div className="command-empty">표시할 지수 히스토리 데이터가 없습니다.</div>
          )}
        </section>
      )}

      {latestNews.length > 0 && (
        <section id="cmd-news" className="card command-panel">
          <h3 className="card-title">{_t("command.latestNews")}</h3>
          <div className="command-news-list">
            {latestNews.map((n, i) => (
              <a key={i} className="command-news-item" href={n.url || "#"} target="_blank" rel="noopener noreferrer">
                <span className="command-news-time">{n.time?.slice(5, 16).replace("T", " ")}</span>
                <span className="command-news-title">{n.title}</span>
                <span className="command-news-source">{n.source}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      <section id="cmd-pulse" className="command-pulse-grid">
        {pulse.map((item) => (
          <button key={item.title} className={`command-pulse-card tone-${item.tone}`} onClick={item.onClick}>
            <span className="command-pulse-title">{item.title}</span>
            <span className="command-pulse-value">{item.value}</span>
            <span className="command-pulse-delta">{item.delta}</span>
          </button>
        ))}
      </section>

      <section id="cmd-movers" className="command-main-grid">
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
                  onDoubleClick={() => { window.location.hash = `analysis/${item.stock_code}`; }}
                >
                  <div className="command-row-rank">{index + 1}</div>
                  <div className="command-row-main">
                    <div className="command-row-title">
                      <button className="link-button font-bold" onClick={(e) => { e.stopPropagation(); openAsset(item.stock_code); }}>{item.stock_name || item.stock_code}</button>
                      <span className="text-secondary">{item.stock_code}</span>
                    </div>
                    <div className="command-row-meta">
                      <span>{item.sector || _t("state.unclassified")}</span>
                      <span>Vol {formatCompact(toNum(item.volume))}</span>
                      {item.stale && <span className="text-warning">{_t("market.stale")}</span>}
                    </div>
                  </div>
                  <div className="command-row-change">
                    <DirectionValue value={toNum(item.change_pct)} suffix="%" />
                    <span className="text-secondary">{formatNumber(toNum(item.price))}</span>
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

      <section id="cmd-candidates" className="card command-panel">
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

      <section id="cmd-detail" className="card command-panel">
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
              <div className="detail-card-value">{selectedMover ? formatNumber(toNum(selectedMover.price)) : "-"}</div>
              <div>{selectedMover ? <DirectionValue value={toNum(selectedMover.change_pct)} suffix="%" /> : "-"}</div>
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
                        <span className="text-secondary">{formatDateTime(order.time)}</span>
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
                      <div className="news-compact-meta">{item.source} · {formatDateTime(item.time)}</div>
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {killModalOpen && (
        <div className="modal-overlay" onClick={() => setKillModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "400px" }}>
            <div className="modal-header">
              <h2 style={{ fontSize: "18px", color: "var(--color-danger)" }}>
                {_t("command.killSwitch")}
              </h2>
              <button onClick={() => setKillModalOpen(false)} className="modal-close">
                ✕
              </button>
            </div>
            <div style={{ marginBottom: "16px", fontSize: "14px" }}>
              <p style={{ marginBottom: "12px", lineHeight: 1.5 }}>
                진행 중인 미체결 주문이 모두 취소되며, 신규 주문이 전면 차단됩니다.<br/>
                현재 보유 중인 포지션은 그대로 유지됩니다.
              </p>
              <label style={{ display: "block", marginBottom: "6px", fontSize: "12px", color: "var(--text-secondary)", fontWeight: "bold" }}>중단 사유 (필수)</label>
              <input 
                type="text" 
                className="input" 
                style={{ width: "100%" }} 
                value={killReason}
                onChange={(e) => setKillReason(e.target.value)}
                placeholder="예: API 연동 장애, 시장 급락, 수동 점검 등"
                autoFocus
              />
            </div>
            <div className="flex gap-sm justify-end">
              <button className="btn" onClick={() => setKillModalOpen(false)}>취소</button>
              <button 
                className="btn btn-danger" 
                disabled={!killReason.trim()}
                onClick={() => {
                  apiPost(`/trading/kill-switch/activate?reason=${encodeURIComponent(killReason)}`).then(() => {
                    setKillModalOpen(false);
                    setKillReason("");
                    void loadData();
                  });
                }}
              >
                차단 실행
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

// Inline helpers removed — use shared imports from lib/formatting.ts and lib/statusMapping.ts

// summarizeDetails imported from lib/formatting.ts

function Badge({ label, tone }: { label: string; tone: import("../lib/statusMapping").BadgeTone }) {
  return <span className={`command-badge tone-${tone}`}>{label}</span>;
}

function StatusBadge({ label, tone }: { label: string; tone: import("../lib/statusMapping").BadgeTone }) {
  return <span className={`command-status-badge tone-${tone}`}>{label}</span>;
}
