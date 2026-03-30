# Critical Gaps

These are the gaps that block a commercial-grade assessment.

## 1. No formal risk policy

The plan mentions risk management, but not a machine-enforced policy set. A commercial trader needs hard limits for exposure, loss, liquidity, concentration, and session behavior.

## 2. No order-state reconciliation model

The document describes order execution and monitoring, but not authoritative recovery after process crash, timeout, duplicate submission, partial fill, or broker desync.

## 3. No durable event architecture

Redis Pub/Sub is acceptable for lightweight signaling, but not as the sole recovery mechanism for production trading events. Critical order and position events need durable storage and replay.

## 4. No production data governance

The plan does not define validation rules for stale prices, malformed news, symbol remaps, corporate actions, calendar exceptions, or feed disagreement.

## 5. No disaster recovery design

The plan does not define:
- backup frequency
- restore testing
- RTO
- RPO
- failover triggers
- degraded mode procedures

## 6. No immutable audit trail

Commercial operation requires a full chronology of:
- inbound market events
- strategy decisions
- risk decisions
- order submissions
- broker acknowledgments
- fill events
- manual operator actions

The plan does not define a tamper-evident audit model.

## 7. No compliance operating layer

There is no retention policy, deployment approval flow, change log discipline, incident sign-off process, or evidence package for external review.

## 8. Local workstation remains too central

The plan correctly identifies MacBook operational risk, but it still keeps the live transition dependent on a workstation-centric architecture until late in the rollout.

## 9. LLM usage lacks guardrails

The plan uses LLMs for sentiment and reporting, but does not define:
- timeout and fallback behavior
- model version pinning
- output validation
- cost ceilings
- provider outage handling
- prompt and result auditability

## 10. Test strategy is not specified at the commercial level

Backtesting and paper trading are not enough. Commercial readiness requires:
- deterministic unit and integration tests
- exchange-session simulation
- broker failure simulation
- chaos and restart testing
- replay testing from recorded events
- reconciliation acceptance tests

