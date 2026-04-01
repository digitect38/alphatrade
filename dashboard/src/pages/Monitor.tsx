import { useEffect, useMemo, useState } from "react";
import DirectionValue from "../components/DirectionValue";
import { apiGet, apiPost } from "../hooks/useApi";
import { toNum, formatNumber, formatCompact } from "../lib/formatting";
import { eventTypeLabel, orderStatusLabel } from "../lib/labels";
import { EXECUTION_ISSUE_STATUSES } from "../lib/statusMapping";
import type { OrderHistoryItem } from "../types";

interface Mover {
  stock_code: string;
  stock_name: string;
  sector: string;
  price: number | string;
  change_pct: number | string;
  volume: number | string;
}

interface EventCandidate {
  stock_code: string;
  stock_name: string;
  event_type: string;
  priority: number;
  details: Record<string, unknown>;
}

type MonitorTab = "movers" | "catalysts" | "tradeable" | "blocked" | "issues";

// EXECUTION_ISSUE_STATUSES → use EXECUTION_ISSUE_STATUSES from lib/statusMapping

export default function MonitorPage({ t: _t, initialTab }: { t: (k: string) => string; initialTab?: string }) {
  const [tab, setTab] = useState<MonitorTab>((initialTab as MonitorTab) || "movers");
  const [movers, setMovers] = useState<Mover[]>([]);
  const [candidates, setCandidates] = useState<EventCandidate[]>([]);
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (initialTab && initialTab !== tab) setTab(initialTab as MonitorTab);
  }, [initialTab]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiGet<{ movers: Mover[] }>("/market/movers?limit=50").then((d) => setMovers(d.movers || [])),
      apiPost<{ candidates: EventCandidate[] }>("/scanner/events").then((d) => setCandidates(d.candidates || [])),
      apiGet<OrderHistoryItem[]>("/order/history?limit=100").then(setOrders),
    ]).catch(() => {}).finally(() => setLoading(false));
  }, []);

  // toNum imported from lib/formatting

  const activeMovers = useMemo(() =>
    movers.filter((m) => Math.abs(toNum(m.change_pct)) >= 0.5)
      .sort((a, b) => Math.abs(toNum(b.change_pct)) - Math.abs(toNum(a.change_pct))),
    [movers]);

  const freshCatalysts = useMemo(() =>
    candidates.filter((c) => c.priority >= 60).sort((a, b) => b.priority - a.priority),
    [candidates]);

  // Simple lane classification
  const tradeable = useMemo(() =>
    candidates.filter((c) => c.priority >= 75).sort((a, b) => b.priority - a.priority),
    [candidates]);

  const blocked = useMemo(() => {
    const orderCodes = new Set(orders.filter((o) => EXECUTION_ISSUE_STATUSES.has(o.status)).map((o) => o.stock_code));
    return candidates.filter((c) => orderCodes.has(c.stock_code) || c.priority < 30)
      .sort((a, b) => b.priority - a.priority);
  }, [candidates, orders]);

  const issueOrders = useMemo(() =>
    orders.filter((o) => EXECUTION_ISSUE_STATUSES.has(o.status)),
    [orders]);

  const goAnalysis = (code: string) => { window.location.hash = `analysis/${code}`; };
  const goBack = () => { window.location.hash = "command"; };

  const tabs: { key: MonitorTab; label: string; count: number }[] = [
    { key: "movers", label: _t("command.activeMovers"), count: activeMovers.length },
    { key: "catalysts", label: _t("command.freshCatalysts"), count: freshCatalysts.length },
    { key: "tradeable", label: _t("command.tradeable"), count: tradeable.length },
    { key: "blocked", label: _t("command.blocked"), count: blocked.length },
    { key: "issues", label: _t("command.executionIssues"), count: issueOrders.length },
  ];

  const fmt = formatNumber;
  const fmtCompact = formatCompact;

  return (
    <div className="page-content">
      {/* Header with back button */}
      <div className="card">
        <div className="flex items-center gap-md" style={{ marginBottom: 12 }}>
          <button className="btn btn-sm" onClick={goBack}>← {_t("nav.command")}</button>
          {loading && <span className="text-secondary">{_t("common.loading")}</span>}
        </div>
        <div className="asset-range-group">
          {tabs.map((t) => (
            <button
              key={t.key}
              className={`asset-range-chip ${tab === t.key ? "is-active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label} ({t.count})
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {tab === "movers" && (
        <div className="card">
          <h3 className="card-title">{_t("command.activeMovers")} — {_t("monitor.clickToAnalyze")}</h3>
          <StockTable
            rows={activeMovers.map((m, i) => ({
              rank: i + 1,
              stock_code: m.stock_code,
              stock_name: m.stock_name || m.stock_code,
              sector: m.sector || "-",
              col1: fmt(toNum(m.price)),
              col1Label: _t("th.price"),
              col2: <DirectionValue value={toNum(m.change_pct)} suffix="%" />,
              col2Label: _t("th.changePct"),
              col3: fmtCompact(toNum(m.volume)),
              col3Label: _t("th.volume"),
            }))}
            onRowClick={goAnalysis}
            emptyText={_t("command.noLiveMovers")}
            t={_t}
          />
        </div>
      )}

      {tab === "catalysts" && (
        <div className="card">
          <h3 className="card-title">{_t("command.freshCatalysts")} — {_t("monitor.clickToAnalyze")}</h3>
          <StockTable
            rows={freshCatalysts.map((c, i) => ({
              rank: i + 1,
              stock_code: c.stock_code,
              stock_name: c.stock_name || c.stock_code,
              sector: eventTypeLabel(c.event_type, _t),
              col1: `${c.priority}`,
              col1Label: _t("command.priority"),
              col2: <span className="text-secondary">{c.event_type}</span>,
              col2Label: _t("command.catalyst"),
              col3: summarize(c.details),
              col3Label: _t("monitor.detail"),
            }))}
            onRowClick={goAnalysis}
            emptyText={_t("command.noCandidatesLane")}
            t={_t}
          />
        </div>
      )}

      {tab === "tradeable" && (
        <div className="card">
          <h3 className="card-title">{_t("command.tradeable")} — {_t("monitor.clickToAnalyze")}</h3>
          <StockTable
            rows={tradeable.map((c, i) => ({
              rank: i + 1,
              stock_code: c.stock_code,
              stock_name: c.stock_name || c.stock_code,
              sector: eventTypeLabel(c.event_type, _t),
              col1: `${c.priority}`,
              col1Label: _t("command.priority"),
              col2: <span className="text-profit font-bold">{_t("state.eligible")}</span>,
              col2Label: _t("monitor.status"),
              col3: summarize(c.details),
              col3Label: _t("monitor.detail"),
            }))}
            onRowClick={goAnalysis}
            emptyText={_t("command.noCandidatesLane")}
            t={_t}
          />
        </div>
      )}

      {tab === "blocked" && (
        <div className="card">
          <h3 className="card-title">{_t("command.blocked")} — {_t("monitor.clickToAnalyze")}</h3>
          <StockTable
            rows={blocked.map((c, i) => ({
              rank: i + 1,
              stock_code: c.stock_code,
              stock_name: c.stock_name || c.stock_code,
              sector: eventTypeLabel(c.event_type, _t),
              col1: `${c.priority}`,
              col1Label: _t("command.priority"),
              col2: <span className="text-loss font-bold">{_t("state.blocked")}</span>,
              col2Label: _t("monitor.status"),
              col3: summarize(c.details),
              col3Label: _t("monitor.detail"),
            }))}
            onRowClick={goAnalysis}
            emptyText={_t("command.noCandidatesLane")}
            t={_t}
          />
        </div>
      )}

      {tab === "issues" && (
        <div className="card">
          <h3 className="card-title">{_t("command.executionIssues")}</h3>
          {issueOrders.length === 0 && <div className="text-secondary" style={{ padding: 20 }}>{_t("exec.noOrders")}</div>}
          {issueOrders.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--color-border)", textAlign: "left" }}>
                    <th style={{ padding: "8px" }}>{_t("th.status")}</th>
                    <th style={{ padding: "8px" }}>{_t("exec.orderId")}</th>
                    <th style={{ padding: "8px" }}>{_t("th.code")}</th>
                    <th style={{ padding: "8px" }}>{_t("th.side")}</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>{_t("th.qty")}</th>
                    <th style={{ padding: "8px" }}>{_t("th.time")}</th>
                    <th style={{ padding: "8px" }}></th>
                  </tr>
                </thead>
                <tbody>
                  {issueOrders.map((o) => (
                    <tr key={o.order_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                      <td style={{ padding: "8px" }}>
                        <span className="text-loss font-bold">{orderStatusLabel(o.status, _t)}</span>
                      </td>
                      <td style={{ padding: "8px", fontSize: 11, fontFamily: "monospace" }}>{o.order_id}</td>
                      <td style={{ padding: "8px", fontWeight: 600 }}>{o.stock_code}</td>
                      <td style={{ padding: "8px" }} className={o.side === "BUY" ? "text-profit" : "text-loss"}>{o.side}</td>
                      <td style={{ padding: "8px", textAlign: "right" }}>{o.quantity}</td>
                      <td style={{ padding: "8px", fontSize: 11 }}>{new Date(o.time).toLocaleString("ko-KR")}</td>
                      <td style={{ padding: "8px" }}>
                        <button className="btn btn-sm" style={{ fontSize: 11 }} onClick={() => goAnalysis(o.stock_code)}>
                          {_t("monitor.analyze")} →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Reusable stock table with click-to-analyze
interface StockRow {
  rank: number;
  stock_code: string;
  stock_name: string;
  sector: string;
  col1: string | React.ReactNode;
  col1Label: string;
  col2: string | React.ReactNode;
  col2Label: string;
  col3: string | React.ReactNode;
  col3Label: string;
}

function StockTable({ rows, onRowClick, emptyText, t: _t }: {
  rows: StockRow[];
  onRowClick: (code: string) => void;
  emptyText: string;
  t: (k: string) => string;
}) {
  if (rows.length === 0) return <div className="text-secondary" style={{ padding: 20 }}>{emptyText}</div>;

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "2px solid var(--color-border)", textAlign: "left" }}>
            <th style={{ padding: "8px", width: 40 }}>#</th>
            <th style={{ padding: "8px" }}>{_t("th.name")}</th>
            <th style={{ padding: "8px" }}>{_t("th.code")}</th>
            <th style={{ padding: "8px" }}>{rows[0]?.col1Label || ""}</th>
            <th style={{ padding: "8px" }}>{rows[0]?.col2Label || ""}</th>
            <th style={{ padding: "8px" }}>{rows[0]?.col3Label || ""}</th>
            <th style={{ padding: "8px", width: 70 }}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.stock_code + r.rank}
              className="monitor-row"
              onClick={() => onRowClick(r.stock_code)}
            >
              <td style={{ padding: "8px", fontWeight: 600 }}>{r.rank}</td>
              <td style={{ padding: "8px", fontWeight: 600 }}>{r.stock_name}</td>
              <td style={{ padding: "8px" }} className="text-secondary">{r.stock_code}</td>
              <td style={{ padding: "8px" }}>{r.col1}</td>
              <td style={{ padding: "8px" }}>{r.col2}</td>
              <td style={{ padding: "8px", fontSize: 12 }} className="text-secondary">{r.col3}</td>
              <td style={{ padding: "8px" }}>
                <span style={{ fontSize: 11, color: "var(--color-accent)" }}>{_t("monitor.analyze")} →</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function summarize(details: Record<string, unknown>) {
  return Object.entries(details).slice(0, 2).map(([k, v]) => `${k}: ${String(v)}`).join(" · ") || "-";
}
