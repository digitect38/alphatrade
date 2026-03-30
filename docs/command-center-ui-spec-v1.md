# Command Center UI Spec

Date:
- 2026-03-30

Scope:
- replacement direction for the current summary-first dashboard structure
- consolidation of the most important operational jobs now spread across:
  - `Dashboard`
  - `Market`
  - `Trend`
  - `Orders`

Primary goal:
- design a main operator screen for fast market-move understanding and safe auto-trading supervision

Related references:
- [ui-capture-review-2026-03-30.md](/Users/woosj/DevelopMac/alpha_trade/docs/ui-capture-review-2026-03-30.md)
- [serious-reanalysis-v1.31.md](/Users/woosj/DevelopMac/alpha_trade/docs/serious-reanalysis-v1.31.md)
- [Dashboard.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Dashboard.tsx)
- [Market.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Market.tsx)
- [Trend.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Trend.tsx)
- [Orders.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Orders.tsx)

Short answer:
- The current UI should stop treating the dashboard as a portfolio summary home.
- The new home screen should be a live operational command center.

---

## 1. Product Intent

The main screen must help the operator answer these questions in under 10 seconds:

1. What is moving right now?
2. Why is it moving?
3. Which candidates are tradeable?
4. Which ones are blocked and why?
5. Did the engine already act?
6. Is the system safe to keep running?

If the screen cannot answer those six questions quickly, it is not the right home screen.

---

## 2. IA Decision

The current top-level pages are too category-based.

Recommended primary IA:

- `Command Center`
- `Market Intel`
- `Execution`
- `Portfolio`
- `System`

Meaning:
- `Command Center` becomes the true landing page
- `Market Intel` replaces the current broad market/trend browsing role
- `Execution` replaces the current raw order page with actual order-state operations
- `Portfolio` keeps longer-horizon holdings and PnL views
- `System` holds health, infra, and audit-oriented views

The current `Dashboard` should be retired as the home page.

---

## 3. Command Center Layout

Recommended desktop layout:

## 3.1 Top status bar

Persistent strip across the page.

Fields:
- market session status
- data freshness
- broker connectivity
- kill switch state
- active risk incidents count
- active execution incidents count
- last update time

Purpose:
- answer immediately whether the operator can trust the system right now

## 3.2 Row A: market pulse

Three to five compact summary cards.

Cards:
- `Active Movers`
- `Fresh Catalysts`
- `Tradeable Candidates`
- `Blocked Candidates`
- `Open Execution Issues`

Rules:
- each card must include both count and change vs recent baseline
- counts must be clickable filters into lower panels

## 3.3 Row B: main split

Main left:
- `Priority Movers`

Main right:
- `Incident Queue`

### Priority Movers

Show 8 to 12 ranked rows or cards only.

Each row must include:
- symbol
- sector
- move magnitude
- acceleration
- catalyst badge
- signal state
- risk state
- execution state

Examples of states:
- `eligible`
- `watch`
- `blocked`
- `submitted`
- `acked`
- `partial`
- `filled`
- `error`

### Incident Queue

Show highest-urgency items only.

Item types:
- stale data
- broker mismatch
- failed order
- unknown order state
- kill switch active
- risk breach

Each item must have:
- severity
- timestamp
- affected symbol or subsystem
- direct action or drilldown

## 3.4 Row C: candidate lanes

Four side-by-side lanes or segmented tabs:

- `Eligible`
- `Blocked`
- `Watching`
- `Executed`

Each candidate card should contain:
- symbol
- sector
- last move
- catalyst reason
- signal strength
- risk checks summary
- current order state

This is where the operator understands system intent.

## 3.5 Row D: selected detail panel

When a row or card is selected, the lower panel updates.

Sections:
- price and intraday context
- latest catalysts
- signal explanation
- risk-check breakdown
- order history
- audit event timeline

This keeps depth out of the top-level layout while preserving traceability.

---

## 4. Panel Specs

## 4.1 Market Pulse Card

Required fields:
- title
- main count
- delta from 5m or 15m baseline
- status color
- drilldown action

Example:
- `Blocked Candidates`
- `7`
- `+3 in last 10m`
- amber

## 4.2 Priority Mover Row

Required fields:
- rank
- symbol and name
- sector
- price change percent
- relative volume
- catalyst badge
- signal badge
- tradeability badge
- execution badge

Rules:
- rows must be sortable by priority score, not just price change
- `0%` and low-priority items do not belong here

## 4.3 Incident Item

Required fields:
- severity
- type
- system or symbol
- age
- short reason
- direct action button

Actions:
- open detail
- retry reconcile
- pause symbol
- acknowledge

## 4.4 Candidate Card

Required fields:
- symbol
- sector
- catalyst summary
- signal summary
- risk block reason or eligibility reason
- order state

Optional fields:
- confidence
- last model update
- liquidity flag

---

## 5. Color And Visual Rules

The current rainbow-style category colors should not be used in dense operational panels.

Command Center color rules:

- green: confirmed positive or safe-go state
- red: confirmed negative move or hard failure
- amber: warning, blocked, degraded, needs review
- blue: informational system status
- gray: neutral or quiet

Restrictions:
- use saturated color only for real meaning
- sector identity should not rely on color
- priority should come from rank, grouping, spacing, and size before color

Typography and spacing:
- one dense but readable display type scale
- compact cards, but with clear section separation
- avoid long tables as the first thing users see

---

## 6. What Moves Out Of The Home Screen

The home screen should not carry everything.

Move these into secondary pages:

- full universe stock table
- exhaustive sector list
- long position table
- historical chart comparison tools
- manual order form as the primary order interface

Those belong in:
- `Market Intel`
- `Portfolio`
- `Execution`

The home screen is for:
- urgency
- actionability
- system safety

---

## 7. Mapping From Current Pages

## 7.1 From `Dashboard`

Keep:
- system status
- high-level portfolio metrics
- kill switch visibility

Reduce:
- large portfolio composition emphasis
- signal count chart as a primary object

Promote:
- live incidents
- blocked candidates
- execution state

## 7.2 From `Market`

Keep:
- live connection status
- fresh market data
- news linkage

Change:
- do not lead with full stock table
- turn key symbols into ranked candidate rows

## 7.3 From `Trend`

Keep:
- sector momentum concept

Change:
- replace exhaustive chip wall with ranked sector cards
- collapse quiet sectors by default
- add catalyst and tradeability context

## 7.4 From `Orders`

Keep:
- order history access

Replace:
- raw manual order form as main execution experience

New execution UI should focus on:
- order state timeline
- broker acknowledgement
- partial fills
- failed/unknown states
- operator intervention actions

---

## 8. Required Backend Support For This UI

The UI redesign should not be implemented against the current broad request-time aggregation shape.

Preferred backend support:

- live market-state snapshot endpoint
- top movers endpoint ranked by priority score
- candidate queue endpoint
- blocked candidates endpoint
- incident feed endpoint
- order/execution state feed endpoint
- audit timeline endpoint by symbol or order

WebSocket events should include:
- tick updates
- candidate state changes
- order state changes
- risk block changes
- system incident events

Without these, the UI will fall back into polling-heavy tables again.

---

## 9. Mobile And Narrow Layout Behavior

On smaller screens:
- top status bar remains fixed
- market pulse cards become horizontal scroll chips
- one primary queue is visible at a time
- selected detail becomes a drawer

Do not try to mirror the full desktop layout on mobile.
Mobile should prioritize:
- incidents
- candidates
- kill switch visibility

---

## 10. Implementation Priority

Recommended order:

1. Create `Command Center` route and layout shell
2. Add top status bar and market pulse cards
3. Replace chip wall with priority movers panel
4. Add incident queue
5. Add candidate lanes
6. Add selected detail panel
7. Move raw tables and manual order tools into secondary pages

---

## 11. Success Criteria

The redesign is successful if an operator can:

- understand market condition in under 5 to 10 seconds
- identify top actionable symbols without scanning the whole universe
- see why a candidate is blocked
- see whether automation already acted
- detect broker or data incidents immediately
- use the page as a live operating surface, not just a browsing screen

---

## 12. Bottom Line

The current UI exposes data.
The new `Command Center` must expose decisions, actionability, and risk state.

That is the core shift.
