# Dashboard

## Planned React analysis dashboard

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| React dashboard exists | Match | `dashboard/src/App.tsx` | Implemented |
| Investment analysis UI pages | Match | `dashboard/src/pages/*.tsx` | `Dashboard`, `Market`, `Trend`, `Analysis`, `Backtest`, `Orders` are present. |
| Portfolio and signal views | Match | `dashboard/src/pages/Dashboard.tsx`, `dashboard/src/components/PortfolioCard.tsx`, `dashboard/src/components/SignalTable.tsx` | Implemented |
| Search/chart/order/system components | Match | `dashboard/src/components/StockSearch.tsx`, `TechnicalChart.tsx`, `OrderHistory.tsx`, `SystemStatus.tsx`, `Toast.tsx` | Implemented |
| REST API integration | Match | `dashboard/src/hooks/useApi.ts` | Implemented |
| WebSocket live updates | Gap | `dashboard/nginx.conf`, repo search | WebSocket support is labeled `future`; no frontend/backend WebSocket implementation was found. |

## Dashboard implementation quality vs plan

| Item | Status | Evidence | Evaluation |
|---|---|---|---|
| Backend proxy from dashboard | Match | `dashboard/nginx.conf` | `/api/` is proxied to `core-engine`. |
| Locale support | Partial | `dashboard/src/hooks/useLocale.ts`, `dashboard/src/App.tsx` | Locale switching exists. Full plan-level polish is harder to confirm from structure alone. |
| Error handling UX | Partial | `dashboard/src/components/Toast.tsx`, `dashboard/src/pages/*` | Toast infrastructure exists, but several pages still use `console.error` or inline local error handling. |
| Styling system | Partial | `dashboard/src/styles.css`, `dashboard/src/pages/Dashboard.tsx`, `dashboard/src/pages/Market.tsx` | A token file exists, but major pages still carry heavy inline styles rather than a consistent shared component styling system. |

## Notable divergence from the plan

| Divergence | Evidence | Impact |
|---|---|---|
| Plan calls for React dashboard plus Grafana for ops monitoring | `dashboard/src/pages/Dashboard.tsx`, `config/grafana/*` | The React dashboard is much more real than the Grafana layer right now, so operational monitoring is underdelivered relative to the plan. |
| Plan expects realtime updates | `dashboard/nginx.conf` | Current dashboard appears request/refresh driven, not event-driven. |
