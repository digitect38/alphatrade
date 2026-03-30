# Remediation Roadmap

## Target state

Move the plan from `prototype / pilot` to `commercially defensible live system`.

## Phase A. Minimum live-trading control package

Complete these before any real-money deployment beyond tightly capped experimentation.

1. Write a formal risk policy.
2. Implement a deterministic order-state machine with idempotency keys.
3. Add broker reconciliation jobs and end-of-day position / cash checks.
4. Add stale-data and bad-data trade blocks.
5. Define kill switches: automatic and manual.
6. Create immutable audit logging for all trade decisions and operator actions.
7. Pin versions for containers, models, dependencies, and API schemas.
8. Move live execution to a dedicated server from day one of real-money trading.

## Phase B. Operational hardening

1. Define backup, restore, RTO, and RPO.
2. Add durable event persistence for order and position events.
3. Build incident runbooks for broker outage, data outage, duplicate orders, and restart recovery.
4. Add secrets rotation, RBAC, image scanning, and dependency scanning.
5. Add deployment promotion gates for strategy and code releases.

## Phase C. Research governance

1. Define promotion criteria from research to paper trading to capital deployment.
2. Add walk-forward validation and regime testing.
3. Track slippage, turnover, latency, and capacity as first-class strategy metrics.
4. Add model and prompt versioning for sentiment components.

## Recommended architecture changes

Change these plan assumptions explicitly:

- Replace `MacBook-first live operation` with `server-first live execution`.
- Replace `Redis Pub/Sub only` with `Redis plus durable event persistence`.
- Replace `dashboard-centric monitoring` with `monitoring plus runbooks plus automated safeguards`.
- Replace `risk engine mentioned` with `risk policy defined, encoded, and tested`.
- Replace `paper trading then live` with `paper trading -> shadow live -> micro-capital -> staged capital increases`.

## Revised commercial verdict after remediation

If the roadmap above is completed, the architecture could become suitable for:
- a small proprietary trading operation
- a controlled commercial pilot

It would still need separate legal and regulatory review before any claim of full commercial deployment readiness.
