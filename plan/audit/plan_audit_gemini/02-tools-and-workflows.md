# Tools and Workflows (Gemini Evaluation)

## 3.1 n8n - Automation Hub

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| n8n as workflow hub | Match | `docker-compose.yml` | Full service with Postgres DB, env config, and persistence. |
| 10 workflow set | Gap | `n8n-workflows/` | Only 1 workflow (`trading-cycle.json`) present. 90% of the planned workflow inventory is missing. |
| News, disclosure, sentiment | Gap | `n8n-workflows/` | No workflows exist for these; currently handled in core-engine Python code. |
| Git-based management | Partial | `n8n-workflows/` | Structure exists, but contains very little code (1 minimal JSON file). |

## 3.2 Grafana - Monitoring Hub

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| Grafana in stack | Match | `docker-compose.yml` | Service exists with appropriate dependencies. |
| Datasource provisioning | Match | `config/grafana/provisioning/datasources/datasources.yml` | Both Prometheus and TimescaleDB are configured. |
| Operational dashboards | Match | `config/grafana/provisioning/dashboards/` | Both `system-health.json` and `trading-performance.json` have been recently populated with multiple panels (improved status since previous audit). |

## 3.3 TradingView - Signal Source

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| TV webhook entry point | Match | `core-engine/app/routes/webhook.py` | `/webhook/tradingview` is fully implemented and publishes to Redis. |
| TV routed through n8n | Gap | `n8n-workflows/` | No n8n workflow bridge for TradingView exists in the repo. Currently, TradingView alerts go directly to the core-engine. |

## 3.4 Operational Stack

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| Prometheus | Match | `config/prometheus/prometheus.yml` | Configured to scrape core-engine, n8n, and prometheus itself. |
| Redis | Match | `core-engine/app/services/redis_publisher.py` | Used for Pub/Sub eventing and KIS token caching. |
| TimescaleDB | Match | `config/timescaledb/init.sql` | Correctly uses hypertables and trading-specific schema. |
| Portainer | Match | `docker-compose.yml` | Service exists for container management. |
