import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DirectionValue from "../components/DirectionValue";
import { apiGet, apiPost } from "../hooks/useApi";
import { eventTypeLabel, orderStatusLabel } from "../lib/labels";
import type { EventCandidate } from "../types";
import type { OrderHistoryItem } from "../types";

interface TrendPoint {
  date: string;
  return_pct: number;
  cumulative: number;
}

interface StockInfo {
  stock_code: string;
  stock_name: string;
  price: number;
}

interface SectorTrend {
  sector: string;
  stock_count: number;
  trend: TrendPoint[];
  cumulative_return: number;
  stocks: StockInfo[];
}

interface SectorOverviewStock {
  stock_code: string;
  stock_name: string;
  price: number;
  change_pct: number;
  volume: number;
}

interface SectorOverview {
  sector: string;
  avg_change: number;
  stock_count: number;
  stocks: SectorOverviewStock[];
}

// EventCandidate imported from types.ts

interface SectorIntel {
  sector: string;
  avgChange: number;
  cumulativeReturn: number;
  stockCount: number;
  positiveBreadth: number;
  negativeBreadth: number;
  flatCount: number;
  breadthScore: number;
  catalystCount: number;
  candidateCount: number;
  blockedCount: number;
  executionCount: number;
  strongestStocks: SectorOverviewStock[];
  weakestStocks: SectorOverviewStock[];
  trend: TrendPoint[];
  priorityScore: number;
  reasons: string[];
}

const EXECUTION_ISSUE_STATUSES = new Set(["REJECTED", "BLOCKED", "FAILED", "UNKNOWN"]);
const EXECUTION_ACTIVE_STATUSES = new Set(["SUBMITTED", "ACKED", "PARTIALLY_FILLED", "FILLED"]);
const QUIET_THRESHOLD = 0.35;

export default function TrendPage({ t }: { t: (k: string) => string }) {
  const [sectorTrends, setSectorTrends] = useState<SectorTrend[]>([]);
  const [overview, setOverview] = useState<SectorOverview[]>([]);
  const [candidates, setCandidates] = useState<EventCandidate[]>([]);
  const [orders, setOrders] = useState<OrderHistoryItem[]>([]);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const openAsset = (code: string) => {
    window.location.hash = `asset/${code}`;
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiGet<{ sectors: SectorTrend[] }>("/index/sectors?days=20"),
      apiGet<{ sectors: SectorOverview[] }>("/index/overview"),
      apiPost<{ candidates: EventCandidate[] }>("/scanner/events"),
      apiGet<OrderHistoryItem[]>("/order/history?limit=50"),
    ])
      .then(([trend, ov, eventScan, orderHistory]) => {
        setSectorTrends(trend.sectors || []);
        setOverview(ov.sectors || []);
        setCandidates(eventScan.candidates || []);
        setOrders(orderHistory || []);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const sectorIntel = useMemo<SectorIntel[]>(() => {
    const trendMap = new Map(sectorTrends.map((item) => [item.sector, item]));
    const candidateStocks = new Map<string, EventCandidate[]>();

    for (const candidate of candidates) {
      if (!candidateStocks.has(candidate.stock_code)) candidateStocks.set(candidate.stock_code, []);
      candidateStocks.get(candidate.stock_code)!.push(candidate);
    }

    return overview.map((sector) => {
      const trend = trendMap.get(sector.sector);
      const positiveBreadth = sector.stocks.filter((stock) => stock.change_pct > 0.5).length;
      const negativeBreadth = sector.stocks.filter((stock) => stock.change_pct < -0.5).length;
      const flatCount = sector.stock_count - positiveBreadth - negativeBreadth;
      const breadthScore = positiveBreadth - negativeBreadth;

      let catalystCount = 0;
      let candidateCount = 0;
      let blockedCount = 0;
      let executionCount = 0;

      for (const stock of sector.stocks) {
        const stockCandidates = candidateStocks.get(stock.stock_code) || [];
        const recentOrder = orders.find((order) => order.stock_code === stock.stock_code);

        if (stockCandidates.length > 0) {
          catalystCount += stockCandidates.length;
          candidateCount += 1;
        }

        if (recentOrder && EXECUTION_ISSUE_STATUSES.has(recentOrder.status)) {
          blockedCount += 1;
        } else if (recentOrder && EXECUTION_ACTIVE_STATUSES.has(recentOrder.status)) {
          executionCount += 1;
        }
      }

      const strongestStocks = [...sector.stocks]
        .sort((a, b) => b.change_pct - a.change_pct)
        .slice(0, 3);
      const weakestStocks = [...sector.stocks]
        .sort((a, b) => a.change_pct - b.change_pct)
        .slice(0, 2);

      const cumulativeReturn = trend?.cumulative_return ?? 0;
      const priorityScore =
        Math.abs(sector.avg_change) * 3 +
        Math.abs(cumulativeReturn) * 0.9 +
        candidateCount * 6 +
        catalystCount * 2.5 +
        Math.abs(breadthScore) * 1.25 +
        executionCount * 2 -
        blockedCount * 1.5;

      const reasons: string[] = [];
      if (candidateCount > 0) reasons.push(`${candidateCount} actionable symbols`);
      if (catalystCount > 0) reasons.push(`${catalystCount} fresh catalysts`);
      if (blockedCount > 0) reasons.push(`${blockedCount} blocked`);
      if (Math.abs(breadthScore) >= 3) reasons.push(`breadth ${breadthScore > 0 ? "strong positive" : "strong negative"}`);
      if (reasons.length === 0) reasons.push("low catalyst density");

      return {
        sector: sector.sector,
        avgChange: sector.avg_change,
        cumulativeReturn,
        stockCount: sector.stock_count,
        positiveBreadth,
        negativeBreadth,
        flatCount,
        breadthScore,
        catalystCount,
        candidateCount,
        blockedCount,
        executionCount,
        strongestStocks,
        weakestStocks,
        trend: trend?.trend || [],
        priorityScore,
        reasons,
      };
    }).sort((a, b) => b.priorityScore - a.priorityScore);
  }, [candidates, orders, overview, sectorTrends]);

  const prioritySectors = useMemo(() => sectorIntel.slice(0, 8), [sectorIntel]);
  const quietSectors = useMemo(
    () => sectorIntel.filter((sector) => Math.abs(sector.avgChange) < QUIET_THRESHOLD && sector.candidateCount === 0).slice(0, 20),
    [sectorIntel],
  );

  useEffect(() => {
    if (!selectedSector && prioritySectors[0]) setSelectedSector(prioritySectors[0].sector);
  }, [prioritySectors, selectedSector]);

  const selectedIntel = sectorIntel.find((item) => item.sector === selectedSector) || prioritySectors[0] || null;
  const selectedOverview = overview.find((item) => item.sector === selectedIntel?.sector) || null;

  const selectedStocks = useMemo(() => {
    if (!selectedOverview) return [];
    return selectedOverview.stocks
      .map((stock) => {
        const stockCandidates = candidates.filter((candidate) => candidate.stock_code === stock.stock_code);
        const recentOrder = orders.find((order) => order.stock_code === stock.stock_code) || null;
        let state = "watching";
        if (recentOrder && EXECUTION_ISSUE_STATUSES.has(recentOrder.status)) state = "blocked";
        else if (recentOrder && EXECUTION_ACTIVE_STATUSES.has(recentOrder.status)) state = "executed";
        else if (stockCandidates.length > 0) state = "eligible";
        return { ...stock, stockCandidates, recentOrder, state };
      })
      .sort((a, b) => {
        const stateScore = stateRank(a.state) - stateRank(b.state);
        if (stateScore !== 0) return stateScore;
        return Math.abs(b.change_pct) - Math.abs(a.change_pct);
      })
      .slice(0, 10);
  }, [candidates, orders, selectedOverview]);

  const sectorAlerts = useMemo(() => {
    const alerts: Array<{ tone: "danger" | "warning" | "info"; title: string; summary: string }> = [];
    for (const sector of prioritySectors) {
      if (sector.catalystCount >= 3) {
        alerts.push({
          tone: "info",
          title: `${sector.sector}: catalyst cluster`,
          summary: `${sector.catalystCount} fresh catalysts across the sector.`,
        });
      }
      if (sector.blockedCount > 0 && sector.candidateCount > 0) {
        alerts.push({
          tone: "warning",
          title: `${sector.sector}: blocked opportunity`,
          summary: `${sector.blockedCount} symbols are blocked despite active setup.`,
        });
      }
      if (Math.abs(sector.avgChange) >= 2 && sector.candidateCount === 0) {
        alerts.push({
          tone: "danger",
          title: `${sector.sector}: move without setup`,
          summary: `Sector is moving ${formatSigned(sector.avgChange)}% but there is no active candidate.`,
        });
      }
    }
    return alerts.slice(0, 6);
  }, [prioritySectors]);

  const summary = useMemo(() => {
    const active = sectorIntel.filter((sector) => Math.abs(sector.avgChange) >= 1).length;
    const accelerating = sectorIntel.filter((sector) => Math.abs(sector.cumulativeReturn) >= 4).length;
    const catalystSectors = sectorIntel.filter((sector) => sector.catalystCount > 0).length;
    const tradeable = sectorIntel.filter((sector) => sector.candidateCount > sector.blockedCount && sector.candidateCount > 0).length;
    return [
      { title: t("trend.activeSectors"), value: active, detail: `${sectorIntel.length} ${t("trend.totalTracked")}`, tone: active > 0 ? "danger" : "neutral" },
      { title: t("trend.accelerating"), value: accelerating, detail: t("trend.strongFollowThrough"), tone: accelerating > 0 ? "info" : "neutral" },
      { title: t("trend.catalystSectors"), value: catalystSectors, detail: t("trend.freshEventConcentration"), tone: catalystSectors > 0 ? "warning" : "neutral" },
      { title: t("trend.tradeableTitle"), value: tradeable, detail: t("trend.containsEligible"), tone: tradeable > 0 ? "success" : "neutral" },
    ];
  }, [sectorIntel, t]);

  const breadthSummary = useMemo(() => {
    const positive = sectorIntel.filter((sector) => sector.breadthScore > 0).length;
    const negative = sectorIntel.filter((sector) => sector.breadthScore < 0).length;
    const strongest = [...sectorIntel].sort((a, b) => b.breadthScore - a.breadthScore)[0];
    const weakest = [...sectorIntel].sort((a, b) => a.breadthScore - b.breadthScore)[0];
    return {
      positive,
      negative,
      strongest: strongest?.sector || "-",
      weakest: weakest?.sector || "-",
      tone: positive > negative + 3 ? t("trend.riskOn") : negative > positive + 3 ? t("trend.riskOff") : t("trend.mixed"),
    };
  }, [sectorIntel]);

  if (loading) return <p className="text-secondary p-xl">{t("common.loading")}</p>;

  return (
    <div className="page-content">
      <section className="trend-intel-summary-grid">
        {summary.map((item) => (
          <div key={item.title} className={`trend-intel-summary-card tone-${item.tone}`}>
            <div className="trend-intel-summary-title">{item.title}</div>
            <div className="trend-intel-summary-value">{item.value}</div>
            <div className="trend-intel-summary-detail">{item.detail}</div>
          </div>
        ))}
      </section>

      <section className="trend-intel-main-grid">
        <div className="card trend-intel-panel">
          <div className="trend-intel-panel-header">
            <div>
              <h3 className="card-title">{t("trend.prioritySectorsTitle")}</h3>
              <p className="trend-intel-panel-subtitle">{t("trend.prioritySectorsSub")}</p>
            </div>
            <span className="text-secondary">{prioritySectors.length} {t("trend.promoted")}</span>
          </div>
          <div className="trend-sector-card-list">
            {prioritySectors.map((sector, index) => (
              <button
                key={sector.sector}
                className={`trend-sector-card ${selectedIntel?.sector === sector.sector ? "is-selected" : ""}`}
                onClick={() => setSelectedSector(sector.sector)}
              >
                <div className="trend-sector-card-top">
                  <div>
                    <div className="trend-sector-rank">#{index + 1}</div>
                    <div className="trend-sector-title">{sector.sector}</div>
                  </div>
                  <DirectionValue value={sector.avgChange} suffix="%" />
                </div>
                <div className="trend-sector-metrics">
                  <span>cum <DirectionValue value={sector.cumulativeReturn} suffix="%" /></span>
                  <span>{sector.stockCount} {t("common.stocks")}</span>
                  <span>{sector.positiveBreadth} up / {sector.negativeBreadth} down</span>
                </div>
                <div className="trend-sector-badges">
                  <TrendBadge tone="info" label={`${sector.catalystCount} catalysts`} />
                  <TrendBadge tone={sector.candidateCount > sector.blockedCount ? "success" : "neutral"} label={`${sector.candidateCount} candidates`} />
                  {sector.blockedCount > 0 ? <TrendBadge tone="warning" label={`${sector.blockedCount} blocked`} /> : null}
                </div>
                <div className="trend-sector-reason">{sector.reasons.join(" · ")}</div>
                <div className="trend-sector-stock-strip">
                  {sector.strongestStocks.map((stock) => (
                    <span key={stock.stock_code} className="trend-stock-chip">
                      <button className="link-button" onClick={(e) => { e.stopPropagation(); openAsset(stock.stock_code); }}>{stock.stock_name}</button>
                    </span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="card trend-intel-panel">
          <div className="trend-intel-panel-header">
            <div>
              <h3 className="card-title">{t("trend.sectorAlertsTitle")}</h3>
              <p className="trend-intel-panel-subtitle">{t("trend.sectorAlertsSub")}</p>
            </div>
          </div>
          <div className="trend-alert-list">
            {sectorAlerts.length === 0 && <div className="trend-empty">{t("trend.noSectorAlerts")}</div>}
            {sectorAlerts.map((alert) => (
              <div key={`${alert.title}-${alert.summary}`} className={`trend-alert-item tone-${alert.tone}`}>
                <div className="trend-alert-title">{alert.title}</div>
                <div className="trend-alert-summary">{alert.summary}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card trend-breadth-strip">
        <div className="trend-breadth-item">
          <span className="trend-breadth-label">{t("trend.marketTone")}</span>
          <span className="trend-breadth-value">{breadthSummary.tone}</span>
        </div>
        <div className="trend-breadth-item">
          <span className="trend-breadth-label">{t("trend.positiveSectors")}</span>
          <span className="trend-breadth-value">{breadthSummary.positive}</span>
        </div>
        <div className="trend-breadth-item">
          <span className="trend-breadth-label">{t("trend.negativeSectors")}</span>
          <span className="trend-breadth-value">{breadthSummary.negative}</span>
        </div>
        <div className="trend-breadth-item">
          <span className="trend-breadth-label">{t("trend.strongestBreadth")}</span>
          <span className="trend-breadth-value">{breadthSummary.strongest}</span>
        </div>
        <div className="trend-breadth-item">
          <span className="trend-breadth-label">{t("trend.weakestBreadth")}</span>
          <span className="trend-breadth-value">{breadthSummary.weakest}</span>
        </div>
      </section>

      <section className="trend-detail-grid">
        <div className="card trend-intel-panel">
          <div className="trend-intel-panel-header">
            <div>
              <h3 className="card-title">{t("trend.selectedSectorDetail")}</h3>
              <p className="trend-intel-panel-subtitle">{t("trend.selectedSectorDetailSub")}</p>
            </div>
            <span className="text-secondary">{selectedIntel?.sector || "-"}</span>
          </div>
          {!selectedIntel && <div className="trend-empty">{t("trend.selectSector")}</div>}
          {selectedIntel && (
            <div className="trend-detail-layout">
              <div className="trend-detail-metrics">
                <div className="trend-detail-card">
                  <div className="trend-detail-label">{t("trend.averageMove")}</div>
                  <div className="trend-detail-value">
                    <DirectionValue value={selectedIntel.avgChange} suffix="%" />
                  </div>
                </div>
                <div className="trend-detail-card">
                  <div className="trend-detail-label">{t("trend.cumulative")}</div>
                  <div className="trend-detail-value">
                    <DirectionValue value={selectedIntel.cumulativeReturn} suffix="%" />
                  </div>
                </div>
                <div className="trend-detail-card">
                  <div className="trend-detail-label">{t("trend.breadth")}</div>
                  <div className="trend-detail-value">{selectedIntel.positiveBreadth}:{selectedIntel.negativeBreadth}</div>
                </div>
                <div className="trend-detail-card">
                  <div className="trend-detail-label">{t("trend.catalysts")}</div>
                  <div className="trend-detail-value">{selectedIntel.catalystCount}</div>
                </div>
              </div>

              <div className="trend-sector-chart">
                {selectedIntel.trend.length > 0 ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={selectedIntel.trend}>
                      <defs>
                        <linearGradient id="sectorTrendFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#1a1a2e" stopOpacity={0.22} />
                          <stop offset="100%" stopColor="#1a1a2e" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" fontSize={11} tickMargin={8} />
                      <YAxis fontSize={11} tickFormatter={(value: number) => `${value}%`} />
                      <Tooltip formatter={(value: number) => `${Number(value).toFixed(2)}%`} />
                      <Area
                        type="monotone"
                        dataKey="cumulative"
                        stroke={selectedIntel.cumulativeReturn >= 0 ? "var(--color-profit)" : "var(--color-loss)"}
                        fill="url(#sectorTrendFill)"
                        strokeWidth={2.5}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="trend-empty">{t("trend.noHistory")}</div>
                )}
              </div>

              <div className="trend-detail-note">
                {selectedIntel.reasons.join(" · ")}
              </div>
            </div>
          )}
        </div>

        <div className="card trend-intel-panel">
          <div className="trend-intel-panel-header">
            <div>
              <h3 className="card-title">{t("trend.sectorCandidates")}</h3>
              <p className="trend-intel-panel-subtitle">{t("trend.sectorCandidatesSub")}</p>
            </div>
            <span className="text-secondary">{selectedStocks.length} {t("trend.visible")}</span>
          </div>
          <div className="trend-candidate-list">
            {selectedStocks.length === 0 && <div className="trend-empty">{t("trend.noStocksSector")}</div>}
            {selectedStocks.map((stock) => (
              <div key={stock.stock_code} className="trend-candidate-row">
                <div className="trend-candidate-main">
                  <div className="trend-candidate-title">
                    <button className="link-button font-bold" onClick={() => openAsset(stock.stock_code)}>{stock.stock_name}</button>
                    <span className="text-secondary">{stock.stock_code}</span>
                  </div>
                  <div className="trend-candidate-meta">
                    <span className={stock.change_pct >= 0 ? "text-up font-heavy" : "text-down font-heavy"}>
                      <DirectionValue value={stock.change_pct} suffix="%" />
                    </span>
                    <span>{stock.price.toLocaleString()}{t("common.won")}</span>
                    <span>Vol {formatCompact(stock.volume)}</span>
                  </div>
                </div>
                <div className="trend-candidate-state">
                  <TrendBadge tone={stock.state === "eligible" ? "success" : stock.state === "blocked" ? "warning" : stock.state === "executed" ? "info" : "neutral"} label={t(`state.${stock.state}`)} />
                  {stock.stockCandidates[0] ? (
                    <TrendBadge tone="info" label={eventTypeLabel(stock.stockCandidates[0].event_type, t)} />
                  ) : (
                    <TrendBadge tone="neutral" label={t("state.noCatalyst")} />
                  )}
                  {stock.recentOrder ? (
                    <TrendBadge tone={EXECUTION_ISSUE_STATUSES.has(stock.recentOrder.status) ? "danger" : "info"} label={orderStatusLabel(stock.recentOrder.status, t)} />
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card trend-intel-panel">
        <div className="trend-intel-panel-header">
          <div>
            <h3 className="card-title">{t("trend.quietSectors")}</h3>
            <p className="trend-intel-panel-subtitle">{t("trend.quietSectorsSub")}</p>
          </div>
        </div>
        <div className="trend-quiet-grid">
          {quietSectors.map((sector) => (
            <button key={sector.sector} className="trend-quiet-chip" onClick={() => setSelectedSector(sector.sector)}>
              <span>{sector.sector}</span>
              <DirectionValue value={sector.avgChange} suffix="%" className="text-secondary" />
            </button>
          ))}
          {quietSectors.length === 0 && <div className="trend-empty">{t("trend.noQuietSectors")}</div>}
        </div>
      </section>
    </div>
  );
}

function formatSigned(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function formatCompact(value: number) {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return `${value}`;
}

function stateRank(state: string) {
  if (state === "eligible") return 0;
  if (state === "blocked") return 1;
  if (state === "executed") return 2;
  return 3;
}

function TrendBadge({ label, tone }: { label: string; tone: "success" | "danger" | "warning" | "info" | "neutral" }) {
  return <span className={`command-badge tone-${tone}`}>{label}</span>;
}
