# Domain Assessment

## 1. Architecture

Assessment: `Partially sufficient`

Strengths:
- The plan correctly keeps analysis, strategy, execution, and monitoring as separate concerns.
- The plan correctly states that investment decisions should stay in custom code, not n8n.
- The move to a separate execution node in live trading is directionally correct.

Weaknesses:
- The control plane is underspecified. The document describes components, but not the exact state machine for degraded modes, failover authority, or order ownership boundaries.
- `n8n -> core engine -> n8n` webhook patterns are described, but delivery guarantees, idempotency keys, replay handling, and exactly-once semantics are not.
- The plan names Redis Pub/Sub for real-time communication, but Pub/Sub alone is weak for durable trading events. A commercial design usually needs durable queues or event logs for recovery and replay.

Plan evidence:
- custom code principle: lines 62, 159-166
- communication pattern: lines 173-178
- live execution split: lines 364-376

## 2. Strategy And Research

Assessment: `Insufficient`

Strengths:
- The plan includes technical analysis, sentiment, sector analysis, correlation, and ensemble signals.
- It includes backtesting and paper-trading phases.

Weaknesses:
- There is no research governance for factor decay, overfitting control, regime change detection, or model retirement.
- No acceptance thresholds are defined for live promotion. For example: minimum out-of-sample duration, turnover bounds, drawdown limits, capacity limits, slippage tolerance, or walk-forward performance gates.
- LLM-based sentiment is included, but there is no measurement framework for drift, hallucination, latency variance, cost spikes, or fallback behavior when LLM providers fail.

Plan evidence:
- sentiment workflow: lines 78, 161, 212
- strategy and backtest phases: lines 162, 213, 216-217

## 3. Risk Management

Assessment: `Materially insufficient`

Strengths:
- The plan mentions a risk engine, order FSM, stop-loss / take-profit monitoring, and a daily loss alert example.

Weaknesses:
- Risk controls are not specified as enforceable policies.
- There is no defined framework for:
  - gross and net exposure limits
  - symbol / sector / strategy concentration limits
  - max order size and participation limits
  - opening auction / closing auction restrictions
  - liquidity screens and halts
  - kill switch authority and automatic trading lockouts
  - stale data detection blocking trade entry
  - duplicate order prevention under retries or reconnects
- A commercial system needs these rules to be deterministic and testable, not implied.

Plan evidence:
- risk engine mention: line 163
- alert example for daily loss: line 121
- execution phase mention: line 214

## 4. Execution And Broker Reliability

Assessment: `Insufficient`

Strengths:
- The plan acknowledges broker integration and execution quality metrics such as fill rate and slippage.
- Separation of analysis from execution in live mode is the right direction.

Weaknesses:
- No explicit lifecycle exists for `created -> submitted -> acknowledged -> partially filled -> filled -> canceled -> rejected -> unknown`.
- No reconciliation design exists between internal order state and broker-reported state.
- No design exists for restart recovery when the process dies between submit and acknowledgment.
- No rate-limit handling, clock synchronization, request signing failure handling, or broker maintenance-window behavior is specified.
- No cancel/replace semantics, partial fill handling, or market-session guardrails are defined.

Plan evidence:
- broker integration: line 164
- order execution API: line 235
- execution metrics panel: line 115
- separate execution node: lines 370-376

## 5. Data Quality

Assessment: `Insufficient`

Strengths:
- The plan centralizes data into TimescaleDB and uses normalization steps.
- It includes multiple feeds: market data, news, and disclosures.

Weaknesses:
- No data quality framework is defined for completeness, timeliness, symbol mapping, corporate actions, duplicate suppression, or bad tick rejection.
- No reference-data stewardship exists for ticker changes, delistings, suspensions, ETFs, rights issues, or exchange calendar anomalies.
- One-minute collection is described, but there is no treatment of late ticks, out-of-order events, or broker-vs-vendor discrepancies.

Plan evidence:
- data collection workflows: lines 76-79
- DB as source of truth: line 296

## 6. Infrastructure And Operations

Assessment: `Not sufficient for commercial production`

Strengths:
- Dockerized services, observability stack, and explicit resource planning are positive.
- The plan recognizes that MacBook live operation has risks and proposes a VPS execution node later.

Weaknesses:
- The plan still relies on a MacBook for development, paper trading, and initial live operation. That is acceptable for prototyping, not for commercial-grade service.
- No backup schedule, restore validation, or infrastructure-as-code discipline is described.
- No RTO/RPO targets, no fault-domain separation, and no documented maintenance procedures are included.
- `latest` container tags appear in the plan; commercial deployments should use pinned, tested versions.

Plan evidence:
- Docker stack: lines 182-199
- MacBook deployment: lines 302-362
- delayed VPS split: lines 375-376

## 7. Monitoring And Incident Response

Assessment: `Partially sufficient`

Strengths:
- Good first-pass observability stack: Prometheus, Grafana, alerts, workflow health.
- The plan tracks API latency, workflow failures, MDD, slippage, and system health.

Weaknesses:
- Monitoring is mostly dashboard-oriented. Commercial operation also needs runbooks, severity definitions, escalation paths, and operator actions.
- No explicit incident taxonomy exists for market data failure, broker outage, delayed fills, duplicate orders, stale portfolio state, or reconciliation breaks.
- No synthetic trading probes or end-to-end canary checks are defined.

Plan evidence:
- Grafana and alerts: lines 109-121
- workflow health checks: line 82

## 8. Security

Assessment: `Insufficient`

Strengths:
- The plan mentions internal-only access, encrypted credentials in tooling, firewall controls, and Cloudflare Tunnel.

Weaknesses:
- There is no secrets lifecycle: creation, storage boundary, rotation cadence, revocation, and break-glass procedure.
- No RBAC model is defined for dashboard, database, workflow editor, and broker credentials.
- No host hardening, image scanning, dependency vulnerability management, or audit logging policy is described.
- No threat model is included for webhook spoofing, replay attacks, token leakage, or insider misuse.

Plan evidence:
- security mentions: lines 95, 199, 360, 362

## 9. Compliance, Audit, And Governance

Assessment: `Missing`

Commercial readiness cannot be claimed without explicit treatment of:
- trade and order record retention
- immutable audit logs
- operator approvals and change management
- access reviews
- production deployment controls
- jurisdiction-specific legal and regulatory obligations

The plan does not cover these areas materially.

## 10. Cost And Schedule Realism

Assessment: `Optimistic`

Strengths:
- The document is explicit about infrastructure and tool cost assumptions.

Weaknesses:
- The budget mainly covers software and hosting, not the control work that makes trading systems safe.
- The schedule understates the effort for reliability engineering, security hardening, reconciliation, and live-ops procedures.
- The savings from n8n and Grafana are real for workflow and dashboard implementation, but they do not remove the need for trading-specific controls.

Plan evidence:
- compressed schedule: lines 205-219
- low operating cost estimates: lines 258-269, 420-434

