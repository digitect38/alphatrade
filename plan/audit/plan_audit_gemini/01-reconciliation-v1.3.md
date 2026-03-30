# AlphaTrade Plan v1.3/v1.31 Reconciliation Report (Gemini)

This report reconciles the current codebase against the **AlphaTrade Development Plan v1.31** and the previous **v1.2 Audit**.

## 1. Refactoring & Core Engine Status (Phase R1-R6)

The codebase strongly aligns with the "Refactoring Success" claims in v1.3.

| Claim | Status | Evidence |
|---|---|---|
| **R1: Code Structure (DI)** | Match | 85+ usages of `Depends` in routes. Core logic separated into `services/` and `analysis/`. |
| **R2: Error Handling & Metrics** | Match | `retry_async` utility implemented and used in all external services (KIS, DART, Naver, n8n). 6+ Prometheus metrics defined in `metrics.py`. |
| **R3: Test Coverage** | Match | 19 test files found in `core-engine/tests/`. Claims 72% coverage (784 tests). |
| **R4: Frontend Modernization** | Match | `useLocale` hook implemented with 100+ translation keys. `useApi` hook uses `apiGet`/`apiPost` abstraction. |
| **R5: Security** | Match | `nginx.conf` configured with security headers and API key proxying. CORS and Rate Limit infrastructure present. |
| **R6: Infrastructure** | Match | Grafana dashboards provisioned with 20+ functional panels. Prometheus scraping 8 services. |

## 2. New Features (v1.3 Additions)

| Feature | Status | Evidence |
|---|---|---|
| **Stock Collection (All KRX)** | Match | `POST /collect/stocks` in `routes/collect.py` fetches 2,600+ stocks from KRX KIND. |
| **Fuzzy Stock Search** | Match | `GET /market/search` in `routes/market.py` implements ILIKE fuzzy search and prefix matching. |
| **Market Scan & Alert** | Match | `POST /alert/scan` in `routes/alert.py` detects news surges, price moves, and major disclosures. |

## 3. Commercial Readiness Gap (v1.31 Focus)

While the core engine is robust (75% complete by self-assessment), there is a significant gap in **Commercial Controls (Phase A)** required for live trading.

| Phase A Task | Status | Note |
|---|---|---|
| **A-1: Risk Policy Enforcement** | Gap | Plan v1.31 defines 2.0% loss limit, 10% position limit, etc. Code for enforcement is not yet fully visible. |
| **A-2/3: Order FSM & Reconciliation** | Gap | Order states exist, but a robust FSM (submitted→acked→filled) and EOD broker reconciliation are missing. |
| **A-5: Kill Switch** | Gap | No dedicated API or automated logic for "Stop All Trading" found. |
| **A-6: Immutable Audit Log** | Gap | `orders` table exists, but "append-only audit log" for all decisions is not implemented. |
| **A-8: VPS Separation** | Partial | Plan now mandates VPS for execution. Repo is currently configured for local-heavy (MacBook) operation. |

## 4. Real-time Architecture Gap

| Feature | Status | Note |
|---|---|---|
| **KIS WebSocket** | Gap | Plan v1.3 targets KIS WebSocket for real-time. Code currently uses REST polling (1-min interval). |
| **Dashboard WebSocket** | Gap | Nginx is configured for `/ws`, but FastAPI `websocket` routers are missing. |

## 5. Summary & Next Steps

The project has successfully transitioned from a "prototype" to a "refactored core". 
**The primary delta between the current code and v1.31 is the "Commercial Control" layer.**

### Recommended Immediate Actions (Priority 1-4):
1. **Implement Risk Policy Engine (A-1)**: Translate the v1.31 risk table into a `RiskManager` service that intercepts all orders.
2. **Implement Kill Switch (A-5)**: Add a global state (Redis) and API to instantly halt all execution.
3. **KIS WebSocket Client (Functional P1)**: Implement the background task for real-time price streaming to replace REST polling.
4. **Expand n8n Workflows (Automation)**: Only 1/10 workflows exist. Port the news/disclosure collection logic to n8n to fulfill the "Hybrid" vision.
