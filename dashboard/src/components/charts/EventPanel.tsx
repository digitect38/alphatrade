/**
 * Collapsible event panel — shows events in a clean table below charts.
 *
 * Reusable in any chart component. Click to expand, scrollable.
 */

import { useState } from "react";
import { getEventColor, type MarketEvent } from "../../lib/events";

export default function EventPanel({
  events,
  t,
  defaultExpanded = false,
}: {
  events: MarketEvent[];
  t: (k: string) => string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!events.length) return null;

  // Category summary counts
  const categoryCounts = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.category] = (acc[e.category] || 0) + 1;
    return acc;
  }, {});

  return (
    <div style={{ marginTop: 8, borderTop: "1px solid var(--color-border-light)", paddingTop: 8 }}>
      <div
        className="flex items-center gap-sm"
        style={{ cursor: "pointer", fontSize: 12, userSelect: "none" }}
        onClick={() => setExpanded((v) => !v)}
      >
        <span style={{ fontSize: 14 }}>{expanded ? "▼" : "▶"}</span>
        <span className="font-bold">{t("analysis.events")} ({events.length})</span>
        <div className="flex gap-sm" style={{ marginLeft: 8 }}>
          {["policy", "geopolitics", "economy", "market", "disaster"].map((cat) => {
            const count = categoryCounts[cat];
            if (!count) return null;
            return (
              <span key={cat} style={{ color: getEventColor(cat), fontSize: 11 }}>
                ■{count}
              </span>
            );
          })}
        </div>
      </div>
      {expanded && (
        <div style={{ marginTop: 6, maxHeight: 200, overflowY: "auto" }}>
          <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
            <tbody>
              {events.map((e) => (
                <tr key={`${e.date}-${e.label}`} style={{ borderBottom: "1px solid #f5f5f5" }}>
                  <td style={{ padding: "3px 6px", whiteSpace: "nowrap", color: "var(--color-text-secondary)" }}>
                    {e.date}
                  </td>
                  <td style={{ padding: "3px 6px" }}>
                    <span style={{ color: getEventColor(e.category), fontWeight: 600 }}>■</span>
                  </td>
                  <td style={{ padding: "3px 6px" }}>
                    {e.url ? (
                      <a
                        href={e.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="event-link"
                        style={{ color: getEventColor(e.category) }}
                      >
                        {e.label}
                      </a>
                    ) : (
                      <span style={{ color: getEventColor(e.category) }}>{e.label}</span>
                    )}
                  </td>
                  <td style={{ padding: "3px 6px", color: "var(--color-text-secondary)" }}>
                    {e.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
