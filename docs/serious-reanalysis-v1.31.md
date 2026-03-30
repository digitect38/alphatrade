# Serious Re-Analysis: Architecture And UI Fitness

Scope:
- `plan/AlphaTrade_Development_Plan_v1.31.md`
- current backend, infrastructure, and dashboard implementation

Primary question:
- Is this architecture and UI actually optimized for fast market-move analysis and safe auto-trading?

Short answer:
- Not yet. The project has become much more complete, but it still behaves more like a broad general-purpose trading platform than a sharp market-move response system.

---

## 1. Executive Verdict

If the true product goal is:
- quick detection of meaningful market moves
- fast operator understanding
- deterministic auto-execution with strong safety

then the current system is only `partially aligned`.

### Current strengths

- The backend already has meaningful trading-domain structure: analysis, strategy, execution, scanner, monitor, alerts, audit, WebSocket, and risk controls.
- The system has moved beyond pure prototype stage.
- Real-time plumbing now exists.

### Current problem

The architecture is still organized around a broad scheduled batch cycle, while the product goal requires an event-first reaction system.

The UI is still organized like a dashboard collection, while the product goal requires an operator cockpit.

That mismatch is the main issue.

---

## 2. Architecture Assessment

## 2.1 Main mismatch: batch cycle vs market-move engine

The core trading loop still runs as a serial full-cycle orchestrator:
- collect OHLCV for the whole universe
- collect news
- generate signals for the whole universe
- execute buys and sells
- monitor positions
- save snapshot

See:
- `core-engine/app/trading/loop.py`

This is acceptable for scheduled portfolio maintenance.
It is weak for rapid market-move response because:
- signal latency grows with universe size
- each cycle mixes collection, analysis, and execution into one long path
- the engine reacts after scanning everything, not when an event becomes important

For a market-move system, the critical path should be:

1. event arrives
2. event is classified
3. only impacted symbols are re-evaluated
4. decision is made
5. execution policy runs

The current loop is closer to `portfolio batch automation` than `event-driven move trading`.

## 2.2 Market data path is still too expensive for fast use

`/market/prices` fetches prices stock-by-stock and waits through the universe:
- `core-engine/app/routes/market.py`

That means:
- API latency scales with active universe size
- the market page is expensive to refresh
- the route is doing aggregation, remote fetch, and sorting on demand

This is the wrong shape for an operator-facing fast market board.

The market board should read from:
- a continuously updated in-memory or Redis-backed snapshot
- precomputed movers lists
- event-ranked candidates

It should not compute the whole board from scratch on request.

## 2.3 Real-time architecture exists, but it is not yet the control center

The project now has:
- KIS WebSocket client
- Redis publish path
- backend WebSocket
- frontend WebSocket hook

See:
- `core-engine/app/services/kis_websocket.py`
- `core-engine/app/routes/ws.py`
- `dashboard/src/hooks/useWebSocket.ts`

This is a good direction.

But the real-time path is still mostly used as a transport layer, not as the core decision architecture.

What is still missing:
- event prioritization
- impacted-symbol recomputation only
- volatility halt / anomaly mode
- fast-path strategy evaluation separate from batch analytics

## 2.4 Trading safety improved, but execution design is still not fully coherent

The project now includes:
- trading guard
- kill switch
- stale data gate
- append-only audit log
- order FSM module

But the execution path still has internal inconsistency between:
- FSM state model
- persisted order statuses
- actual order manager path

This makes the architecture look stronger on paper than it is in runtime behavior.

For real auto-trading, this is critical because execution correctness matters more than analytics depth.

## 2.5 n8n is still positioned too broadly for a speed-sensitive product

n8n is useful for:
- reports
- notifications
- daily/weekly jobs
- health checks
- non-critical orchestration

It should not sit near the critical trading reaction path for fast market moves.

The plan says the core logic stays in code, which is correct.
But the system narrative still gives n8n too much architectural importance relative to the actual product goal.

For this product, the center should be:
- real-time feed
- fast symbol ranking
- event-driven strategy engine
- safe execution node

not workflow automation.

---

## 3. UI Assessment

## 3.1 Main mismatch: dashboard pages vs operator cockpit

The UI is readable, but it is not yet optimized for the primary job:
- detect what is moving now
- understand why it matters
- decide whether automation should act
- inspect current risk and execution state instantly

Current pages are spread by category:
- Dashboard
- Market
- Trend
- Analysis
- Orders

That is reasonable for a generic product.
It is not optimal for a fast market operator.

## 3.2 Dashboard page is too summary-oriented

`dashboard/src/pages/Dashboard.tsx` shows:
- total value
- daily pnl
- return
- MDD
- positions
- signals
- quick actions

This is useful, but the main view still answers:
- "How is the system doing overall?"

more than:
- "What is moving right now and what action is required?"

For a market-move trading product, the main screen should prioritize:
- live movers
- alert queue
- strategy candidates
- open risk incidents
- execution exceptions
- kill switch state

before long-horizon portfolio summaries.

## 3.3 Market page is closer to the goal, but still too passive

`dashboard/src/pages/Market.tsx` is the closest page to the product goal.
It has:
- live connection state
- stock table
- news counts
- scan action

But it still behaves like a data table, not a decision board.

Missing for serious use:
- ranking by event importance, not just latest percent move
- alert clustering by reason
- symbol cards with catalyst + liquidity + signal + risk block state
- operator triage view: `watch`, `eligible`, `blocked`, `executed`
- visible stale-data and execution-state badges

## 3.4 Orders page is too raw for production operation

`dashboard/src/pages/Orders.tsx` supports manual order entry, but it is still a basic form.

For real operator use, the page needs:
- pre-trade check preview before submit
- live kill switch status in view
- order intent vs actual broker status
- duplicate protection visibility
- rejection reasons and recovery actions
- open orders, partial fills, unknown states

Without that, the operator sees the API result, not the execution system.

## 3.5 Visual system is cleaner, but not purpose-built

The CSS is much better than before, but the visual language is still generic admin dashboard design:
- white cards
- simple metrics
- neutral data tables

That is safe, but it does not help high-speed attention routing.

For this domain, design should emphasize:
- hierarchy by urgency
- stronger state colors
- dense but scannable layouts
- pinned action rail
- persistent risk strip
- differentiated visual zones for `market`, `risk`, `execution`, `alerts`

Right now the UI is cleaner than before, but still not specialized enough.

---

## 4. What The Product Actually Needs

If the real product is `quick analysis of market move + auto-trading`, the architecture should be reframed around 4 cores.

## 4.1 Core A: Event Intake

Sources:
- KIS real-time ticks
- news events
- disclosures
- TradingView auxiliary alerts

Need:
- normalized event bus
- event priority scoring
- symbol impact classification

## 4.2 Core B: Decision Engine

Need two layers:

- Fast path:
  - re-evaluate only impacted symbols
  - use lightweight strategy/risk checks
  - respond in seconds

- Slow path:
  - scheduled enrichment
  - deeper analytics
  - daily/weekly model refresh

Current implementation mixes these too much.

## 4.3 Core C: Execution Safety Node

Need:
- dedicated live execution service
- coherent FSM and reconciliation
- broker truth synchronization
- hard trade blocks

This must be the most reliable component in the system.

## 4.4 Core D: Operator Cockpit

Main screen should unify:
- live movers
- active alerts
- trade candidates
- blocked candidates and why
- open positions with stop/take-profit status
- kill switch and broker health

The current multi-page UI should become secondary navigation, not the primary operating model.

---

## 5. Recommended Architecture Changes

## Priority 1. Split fast path from batch path

Keep:
- batch trading cycle for maintenance and end-of-day updates

Add:
- event-driven symbol recompute path for live moves

This is the most important change.

## Priority 2. Build a market state cache

Create a continuously updated state store for:
- last price
- percent move
- volume surge
- news count
- alert count
- risk block state
- signal state

The UI and quick APIs should read from this cache, not rebuild from remote calls.

## Priority 3. Promote scanner to first-class engine

The scanner should become:
- the live event triage engine
- not just a morning scan utility

It should classify:
- momentum break
- volume spike
- disclosure shock
- news cluster
- sector sympathy move

## Priority 4. Reduce n8n from core narrative to support narrative

n8n should remain for:
- notifications
- reports
- scheduled maintenance
- health checks

It should not define the product identity.

## Priority 5. Normalize execution state model

Unify:
- code FSM
- database status enum
- API response statuses
- dashboard status labels

This is mandatory before serious auto-trading use.

---

## 6. Recommended UI Changes

## New primary page: `Command Center`

Replace the current summary-first landing page with a command center containing:

- live movers panel
- alert stream panel
- eligible trade candidates panel
- blocked candidates panel
- execution incidents panel
- portfolio risk strip
- kill switch / broker health strip

## New page role definitions

- `Command Center`: real-time action
- `Market`: deeper tape and catalyst review
- `Execution`: orders, fills, rejects, unknowns, reconciliation
- `Portfolio`: holdings and risk exposure
- `Research`: analysis, trend, backtest

Current page boundaries are too generic.

## UI behavior changes

- Use streaming updates by default on key screens
- Remove manual refresh as the main interaction
- Add persistent system/risk header
- Add explicit badges: `LIVE`, `STALE`, `BLOCKED`, `EXECUTED`, `REJECTED`, `UNKNOWN`
- Add one-click drilldown from alert to symbol context

## Visual design changes

- Use stronger semantic layout zones
- Increase information density on desktop
- Reduce decorative spacing on action screens
- Make urgent items impossible to miss

---

## 7. Practical Build Order

1. Fix execution model consistency.
2. Build live market-state cache and movers API.
3. Add event-priority scanner for impacted symbols only.
4. Build `Command Center` page.
5. Build `Execution` page with true lifecycle visibility.
6. Relegate batch workflows and reports to secondary operations.

---

## 8. Final Judgment

The project is no longer a toy.

But if the intended product is truly:
- fast market-move analysis
- auto-trading
- operator-grade control

then the current architecture and UI still need one serious shift:

**from broad platform completeness to fast-path trading focus**

That means:
- event-first backend
- cache-first market APIs
- execution-first safety model
- cockpit-first UI

Without that shift, the system can remain feature-rich while still underperforming at its actual job.

