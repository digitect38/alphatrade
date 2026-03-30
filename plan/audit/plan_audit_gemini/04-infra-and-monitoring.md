# Infrastructure and Monitoring (Gemini Evaluation)

## 5. Docker Compose Alignment

| Service | Status | Evidence | Evaluation |
|---|---|---|---|
| `timescaledb` | Match | `docker-compose.yml` | Fully configured with persistent volumes. |
| `redis` | Match | `docker-compose.yml` | Used for pub/sub and caching. |
| `n8n` | Match | `docker-compose.yml` | Full service with dedicated Postgres DB. |
| `core-engine` | Match | `docker-compose.yml` | Built from local Dockerfile. |
| `dashboard` | Match | `docker-compose.yml` | Vite production build served via Nginx. |
| `prometheus` | Match | `docker-compose.yml` | Central metrics collection. |
| `grafana` | Match | `docker-compose.yml` | Integrated with Prometheus/TimescaleDB. |
| `portainer` | Match | `docker-compose.yml` | Optional but present for management. |

## Monitoring Implementation

| Detail | Status | Evidence | Evaluation |
|---|---|---|---|
| Metrics endpoint | Match | `core-engine/app/main.py` | `/metrics` is exposed for Prometheus. |
| Dashboard provisioning | Match | `config/grafana/provisioning/` | Functional dashboards now exist. |
| Panel coverage | Match | `system-health.json`, `trading-performance.json` | 20+ panels covering HTTP metrics, system health, and trading performance. |
| Hypertables | Match | `config/timescaledb/init.sql` | 7 tables converted to hypertables for time-series optimization. |

## Infrastructure Divergence

- **Secrets**: The plan mentions Docker Secrets, but the implementation currently uses `.env` files and environment variables in `docker-compose.yml`.
- **Nginx Reverse Proxy**: While the dashboard includes Nginx, there is no top-level "Gateway" or "Reverse Proxy" container managing access to all services (n8n, Grafana, Portainer).
