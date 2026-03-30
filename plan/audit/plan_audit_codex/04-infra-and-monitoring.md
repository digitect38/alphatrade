# Infra And Monitoring

## 5. Docker Compose plan

| Planned container | Status | Evidence | Evaluation |
|---|---|---|---|
| `timescaledb` | Match | `docker-compose.yml` | Present |
| `redis` | Match | `docker-compose.yml` | Present |
| `n8n` | Match | `docker-compose.yml` | Present |
| `core-engine` | Match | `docker-compose.yml` | Present |
| `dashboard` | Match | `docker-compose.yml` | Present |
| `prometheus` | Match | `docker-compose.yml` | Present |
| `grafana` | Match | `docker-compose.yml` | Present |
| `portainer` | Match | `docker-compose.yml` | Present |

## Compose-level details

| Planned detail | Status | Evidence | Evaluation |
|---|---|---|---|
| Shared Docker network `alphatrade-net` | Match | `docker-compose.yml` | Implemented exactly as planned. |
| Healthchecks per service | Match | `docker-compose.yml` | Implemented for major services. |
| External access controlled by reverse proxy | Partial | `dashboard/nginx.conf`, `docker-compose.yml` | Dashboard includes nginx, but there is no top-level dedicated reverse proxy service for the whole stack. `cloudflared` is optional and separate. |
| Secrets via Docker Secrets or `.env` | Partial | `docker-compose.yml` | `.env`-style environment variables are used; Docker Secrets are not implemented. |

## Monitoring stack

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| Prometheus scrape endpoint | Match | `core-engine/app/main.py`, `config/prometheus/prometheus.yml` | `/metrics` exists and is scraped. |
| HTTP metrics | Match | `core-engine/app/metrics.py`, `core-engine/app/middleware.py` | Request counters and latency metrics exist. |
| Business metrics | Match | `core-engine/app/metrics.py` | Order, signal, portfolio value, and collection metrics exist. |
| Grafana operational dashboards | Gap | `config/grafana/provisioning/dashboards/*.json` | Provisioning exists, but dashboard payloads are effectively empty. |
| n8n metrics integrated into operations view | Partial | `config/prometheus/prometheus.yml` | Prometheus is set to scrape n8n, but no completed Grafana panel set proves usable visualization yet. |

## Database alignment

| Planned item | Status | Evidence | Evaluation |
|---|---|---|---|
| TimescaleDB hypertables for time series | Match | `config/timescaledb/init.sql` | `ohlcv`, `news`, `disclosures`, `sentiment_scores`, `strategy_signals`, `orders`, `portfolio_snapshots` are hypertables. |
| Trading-related schema coverage | Match | `config/timescaledb/init.sql` | Stocks, universe, positions, signals, orders, and snapshots are covered. |
| Constraints and indexes | Match | `config/timescaledb/init.sql` | CHECK constraints and indexes are present. |
