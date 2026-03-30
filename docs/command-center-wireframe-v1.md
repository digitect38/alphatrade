# Command Center Wireframe

Date:
- 2026-03-30

Scope:
- practical wireframe for the `Command Center` landing page
- based on the current implementation in `dashboard/src/pages/CommandCenter.tsx`
- intended to guide the next UI restructuring pass

References:
- [command-center-ui-spec-v1.md](/Users/woosj/DevelopMac/alpha_trade/docs/command-center-ui-spec-v1.md)
- [ui-capture-review-2026-03-30.md](/Users/woosj/DevelopMac/alpha_trade/docs/ui-capture-review-2026-03-30.md)
- [CommandCenter.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/CommandCenter.tsx)
- [App.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/App.tsx)

Short answer:
- A basic `Command Center` page already exists.
- It is a useful starting point, but it is still only a thin live summary.
- The next version should become a real operating surface.

---

## 1. Current vs Target

Current `CommandCenter.tsx` already has:
- top status strip
- live movers list
- event candidates list
- scan action
- kill switch action

That is a valid first step.

It still lacks:
- market pulse summary cards
- blocked vs eligible candidate separation
- incident queue
- selected symbol detail pane
- execution-state visibility
- stronger visual hierarchy

So the right move is not to replace it completely.
It is to expand and restructure it.

---

## 2. Desktop Wireframe

Recommended desktop structure:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ PAGE TITLE: Command Center                                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ TOP STATUS BAR                                                              │
│ [LIVE/OFFLINE] [SESSION] [DATA FRESHNESS] [BROKER] [KILL SWITCH] [RISK]     │
│ [EXEC INCIDENTS] [LAST UPDATE]                               [SCAN] [PAUSE] │
├──────────────────────────────────────────────────────────────────────────────┤
│ MARKET PULSE                                                                │
│ [Active Movers] [Fresh Catalysts] [Tradeable] [Blocked] [Exec Issues]       │
├───────────────────────────────────────────────┬──────────────────────────────┤
│ PRIORITY MOVERS                               │ INCIDENT QUEUE               │
│ 1. Symbol / Sector / Move / Catalyst / State  │ Critical and warning items   │
│ 2. Symbol / Sector / Move / Catalyst / State  │ stale feed                   │
│ 3. Symbol / Sector / Move / Catalyst / State  │ broker mismatch              │
│ ...                                           │ failed order                 │
│                                               │ unknown state                │
├───────────────────────────────────────────────┴──────────────────────────────┤
│ CANDIDATE LANES                                                             │
│ [Eligible] [Blocked] [Watching] [Executed]                                  │
│ card card card                                                              │
│ card card card                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ SELECTED DETAIL                                                             │
│ [Intraday] [Catalysts] [Signal] [Risk Checks] [Order Timeline] [Audit]      │
│ detailed panel for selected symbol or event                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

This is the recommended end-state layout for desktop.

---

## 3. Panel Details

## 3.1 Top Status Bar

Purpose:
- tell the operator whether the system can be trusted right now

Fields:
- market session status
- websocket/live status
- data freshness age
- broker connectivity
- kill switch state
- daily loss state
- open incident count
- last refresh time

Actions:
- `Scan Now`
- `Activate Kill Switch` or `Resume`

Current mapping:
- already partially implemented in [CommandCenter.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/CommandCenter.tsx)

Needed improvements:
- add explicit data freshness badge
- separate broker health from session state
- add incident count summary
- remove emoji-heavy presentation and move toward semantic badges

## 3.2 Market Pulse Row

Purpose:
- provide immediate market shape summary before reading lists

Cards:
- `Active Movers`
- `Fresh Catalysts`
- `Tradeable Candidates`
- `Blocked Candidates`
- `Execution Issues`

Each card should include:
- main count
- short delta vs baseline
- semantic color
- click behavior to filter lower panels

Current state:
- missing

Priority:
- high

## 3.3 Priority Movers Panel

Purpose:
- show what matters now, not the whole universe

Each row should contain:
- rank
- symbol and name
- sector
- move percent
- acceleration or relative volume
- catalyst badge
- signal badge
- tradeability badge
- execution badge

Current state:
- partially present as `Live Movers`

Gaps in current implementation:
- missing catalyst
- missing eligibility vs blocked state
- missing execution state
- missing ranking explanation
- no selection interaction

## 3.4 Incident Queue Panel

Purpose:
- pull urgent system or execution failures into one place

Required incident types:
- stale feed
- broker mismatch
- failed order
- unknown order state
- reconciliation mismatch
- kill switch active
- rate limit or upstream failure

Each item should show:
- severity
- age
- short description
- direct action

Current state:
- missing

Priority:
- very high

## 3.5 Candidate Lanes

Purpose:
- show the engine's current intent in a way an operator can verify quickly

Lanes:
- `Eligible`
- `Blocked`
- `Watching`
- `Executed`

Each candidate card:
- symbol
- sector
- catalyst
- signal strength
- reason summary
- risk state
- order state

Current state:
- partially implied by `Event Candidates`

Gaps:
- all candidates are mixed into one list
- no blocked reason
- no execution transition visibility
- no lifecycle grouping

## 3.6 Selected Detail Panel

Purpose:
- keep the top of the page focused while still allowing drilldown

Tabs:
- `Price`
- `Catalysts`
- `Signal`
- `Risk`
- `Order Timeline`
- `Audit`

Current state:
- missing

Priority:
- medium-high

---

## 4. Recommended Visual Hierarchy

The page should read in this order:

1. system trust state
2. market pulse summary
3. most important movers
4. incidents
5. candidate intent
6. selected detail

This should be obvious from layout alone.

Rules:
- do not use rainbow identity colors
- use consistent semantic colors
- use dense but calm cards
- reserve the strongest colors for danger, blocks, and exceptional moves
- keep tables secondary, not primary

---

## 5. Mobile Wireframe

Recommended narrow layout:

```text
┌──────────────────────────────┐
│ Command Center               │
├──────────────────────────────┤
│ Top Status Strip             │
├──────────────────────────────┤
│ Pulse Cards (horizontal)     │
├──────────────────────────────┤
│ Priority Movers              │
├──────────────────────────────┤
│ Incident Queue               │
├──────────────────────────────┤
│ Candidate Lanes (tabs)       │
├──────────────────────────────┤
│ Detail Drawer                │
└──────────────────────────────┘
```

Mobile rules:
- keep top status always visible
- use tabs for lanes
- open selected details in a drawer or stacked panel
- do not attempt multi-column density

---

## 6. Build Sequence

Recommended implementation sequence:

1. strengthen top status bar
2. add market pulse cards
3. split current right panel into `Incident Queue` and `Candidate Lanes`
4. upgrade `Live Movers` into ranked priority movers
5. add selected detail panel
6. move less-urgent tables to secondary pages

---

## 7. Backlog Mapping

Immediate UI backlog:

- add `Market Pulse` row to `CommandCenter.tsx`
- split `Event Candidates` into grouped lanes
- add incident feed section
- add selected-item state
- add detail tabs below the main grid
- normalize semantic badges and colors

Secondary backlog:

- reduce `Dashboard` home importance
- move summary metrics into `Portfolio`
- convert `Trend` into `Market Intel`
- replace `Orders` primary form experience with lifecycle-first execution page

---

## 8. Success Check

The wireframe is successful if a user can:
- open the page and know whether the system is safe
- identify the top 5 actionable symbols quickly
- distinguish eligible vs blocked candidates immediately
- spot incidents without reading large tables
- drill into one symbol without losing page context

---

## 9. Bottom Line

The current `Command Center` should be treated as a seed, not a finished design.

The next version should become:
- less like a pair of live lists
- more like a ranked operational cockpit
