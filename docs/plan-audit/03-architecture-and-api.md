# Architecture And API

## 4.1 Hybrid architecture blocks

| Planned block | Status | Evidence | Evaluation |
|---|---|---|---|
| Data collection | Match | `core-engine/app/routes/collect.py` | News, disclosures, OHLCV, and stock master collection endpoints exist. |
| Analysis engine | Match | `core-engine/app/analysis/*`, `core-engine/app/routes/analysis.py` | Technical, volume, sector, sentiment, correlation, and causality features exist. |
| NLP sentiment hybrid layer | Partial | `core-engine/app/analysis/sentiment.py`, `core-engine/app/routes/analysis.py` | Python sentiment analysis exists, but the n8n AI-node routing described in the plan is not visible in repo workflows. |
| Strategy engine | Match | `core-engine/app/strategy/*`, `core-engine/app/routes/strategy.py` | Signal generation, batch signal generation, and backtesting exist. |
| Execution engine | Match | `core-engine/app/execution/*`, `core-engine/app/routes/order.py`, `core-engine/app/routes/trading.py` | Order execution, broker access, monitoring, and risk checks exist. |
| Broker integration | Match | `core-engine/app/services/kis_api.py`, `core-engine/app/execution/broker.py` | KIS integration exists. |
| Notification/reporting via tools | Partial | `core-engine/app/services/notification.py`, `core-engine/app/routes/alert.py` | Alerting exists in code, but the planned n8n-centered report automation is not evidenced. |
| Monitoring layer | Partial | `config/prometheus/prometheus.yml`, `config/grafana/*` | Monitoring stack exists, but Grafana dashboards are unfinished. |
| React analysis dashboard | Match | `dashboard/src/App.tsx`, `dashboard/src/pages/*.tsx` | Dashboard exists and consumes backend APIs. |

## 4.2 Communication patterns

| Planned communication | Status | Evidence | Evaluation |
|---|---|---|---|
| `n8n -> analysis engine` via REST | Partial | `core-engine/app/main.py`, `core-engine/app/routes/*` | The REST API exists and is suitable for n8n calls, but the exported n8n workflows showing that usage are mostly absent. |
| `analysis engine -> n8n` via webhook | Gap | repo search | No code path clearly calls back into n8n webhooks. |
| Engine to DB via SQL | Match | `core-engine/app/database.py`, route and service modules, `config/timescaledb/init.sql` | Core engine uses DB pool access and SQL-backed persistence. |
| Realtime module communication via Redis pub/sub | Match | `core-engine/app/services/redis_publisher.py`, `core-engine/app/routes/webhook.py`, `core-engine/app/trading/loop.py` | Event publication is implemented for OHLCV, TradingView, orders, scan events, and cycle completion. |
| React dashboard via WebSocket + REST | Partial | `dashboard/nginx.conf`, repo search | REST is implemented. WebSocket is explicitly marked as future work. |
| Prometheus to Grafana | Partial | `config/prometheus/prometheus.yml`, `config/grafana/provisioning/datasources/datasources.yml` | Data path is configured, but useful dashboards are not yet present. |

## 7.1 Planned FastAPI endpoints

| Planned endpoint | Status | Evidence | Notes |
|---|---|---|---|
| `POST /analyze/technical` | Match | `core-engine/app/routes/analysis.py` | Implemented |
| `POST /analyze/sentiment` | Match | `core-engine/app/routes/analysis.py` | Implemented |
| `POST /analyze/correlation` | Match | `core-engine/app/routes/analysis.py` | Implemented |
| `POST /strategy/signal` | Match | `core-engine/app/routes/strategy.py` | Implemented |
| `POST /order/execute` | Match | `core-engine/app/routes/order.py` | Implemented |
| `GET /portfolio/status` | Match | `core-engine/app/routes/portfolio.py` | Implemented |
| `GET /metrics` | Match | `core-engine/app/main.py` | Implemented |
| `POST /webhook/tradingview` | Match | `core-engine/app/routes/webhook.py` | Implemented |

## Additional API coverage beyond the plan examples

| Area | Evidence |
|---|---|
| Collection APIs | `core-engine/app/routes/collect.py` |
| Market data APIs | `core-engine/app/routes/market.py` |
| Scanner APIs | `core-engine/app/routes/scanner.py` |
| Alert APIs | `core-engine/app/routes/alert.py` |
| Index/sector APIs | `core-engine/app/routes/index.py` |
| Trading status/snapshot/monitor APIs | `core-engine/app/routes/trading.py` |

Observed route count from router decorators: 37 endpoints.
