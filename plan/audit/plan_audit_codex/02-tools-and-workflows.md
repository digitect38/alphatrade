# Tools And Workflows

## 3.1 n8n

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| n8n as workflow automation hub | Match | `docker-compose.yml` | `n8n` service is defined with Postgres backend, auth, timezone, volume, and healthcheck. |
| 10 workflow set `WF-01` to `WF-10` | Gap | `n8n-workflows/trading-cycle.json` | Repo contains one workflow file only. The planned workflow inventory is not present as code/exported JSON. |
| News, disclosure, sentiment, OHLCV, alert, daily report, healthcheck, TradingView, weekly review, universe refresh workflows | Gap | `n8n-workflows/` | No separate workflow exports for these planned flows were found. |
| n8n Git-based workflow management | Partial | `n8n-workflows/trading-cycle.json` | Workflows are stored in git, but only one exported workflow is present. |
| Failure/retry/alert operationalization | Partial | `docker-compose.yml` and repo search | Container healthchecks exist, but workflow-level retry/alert logic is not visible from exported workflows. |

## Observed n8n implementation

| Item | Value |
|---|---|
| Workflow file count | 1 |
| Workflow name | `Trading Cycle` |
| Node count | 2 |
| Trigger evidence | `Every 1 Minute` |

## 3.2 Grafana

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| Grafana included in stack | Match | `docker-compose.yml` | Service exists and depends on Prometheus and TimescaleDB. |
| Datasource provisioning | Match | `config/grafana/provisioning/datasources/datasources.yml` | Prometheus and TimescaleDB datasources are configured. |
| Operational dashboards | Partial | `config/grafana/provisioning/dashboards/dashboards.yml` | Dashboard provisioning is wired, but content is not complete. |
| System/API/trading/order/alert dashboards populated | Gap | `config/grafana/provisioning/dashboards/system-health.json`, `config/grafana/provisioning/dashboards/trading-performance.json` | Both JSON files currently have no `title` and no panels. |

## 3.3 TradingView

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| TradingView webhook entry point | Match | `core-engine/app/routes/webhook.py` | `/webhook/tradingview` exists, validates secret, logs, and publishes Redis events. |
| TradingView as auxiliary signal source only | Partial | `core-engine/app/routes/webhook.py`, `core-engine/app/strategy/ensemble.py` | Webhook ingestion exists and ensemble logic exists, but the explicit full `TradingView -> n8n -> strategy engine` path is not present in repo exports. |
| TradingView routed through n8n workflow | Gap | `n8n-workflows/` | No exported n8n workflow showing this bridge was found. |

## 3.4 Other tools

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| Prometheus | Match | `docker-compose.yml`, `config/prometheus/prometheus.yml` | Implemented and scrapes `core-engine`, `n8n`, and `prometheus`. |
| Redis | Match | `docker-compose.yml`, `core-engine/app/services/redis_publisher.py` | Implemented for caching and pub/sub style event publication. |
| TimescaleDB | Match | `docker-compose.yml`, `config/timescaledb/init.sql` | Implemented with hypertables and trading-related schema. |
| Portainer | Match | `docker-compose.yml` | Included as planned. |
| Airflow | N/A | repo search | Optional in plan; not present. |
| Google Sheets | N/A | repo search | Optional/integration-level; not present. |
| Uptime Kuma | N/A | repo search | Planned for later phase; not present. |
