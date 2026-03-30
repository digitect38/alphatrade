# UI Capture Review

Date:
- 2026-03-30

Scope:
- captured screen in `capture/스크린샷 2026-03-30 오후 11.19.30.png`
- current dashboard pages
- current product goal: fast market-move understanding and safe auto-trading

Referenced assets:
- [스크린샷 2026-03-30 오후 11.19.30.png](/Users/woosj/DevelopMac/alpha_trade/capture/스크린샷%202026-03-30%20오후%2011.19.30.png)
- [Trend.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Trend.tsx)
- [Dashboard.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Dashboard.tsx)

Primary question:
- What is wrong with the current UI when judged as an operator interface for rapid market analysis and auto-trading?

Short answer:
- The UI is functional, but it is not organized as an operator cockpit.
- The captured `Trend` page is the clearest example: too much equal-weight information, weak visual hierarchy, no action path, and poor signal-to-noise ratio.

---

## 1. Executive Verdict

The current UI is closer to:
- a data browser
- a category-based dashboard collection

It is not yet:
- a fast-decision trading console

This is not mainly a styling problem.

This is mainly:
- an information architecture problem
- a visual hierarchy problem
- an operator workflow problem

---

## 2. What The Capture Shows

The captured `Trend` screen displays a very large set of sector chips with:
- equal prominence
- strong, saturated colors
- tiny numeric changes
- many entries showing `+0%`

The practical result is:
- visual overload
- poor scanability
- weak prioritization
- almost no direct decision support

A user opening this screen cannot quickly answer:
- what is actually moving now
- what matters most
- what is tradeable
- what is blocked
- what needs action first

That is the core failure.

---

## 3. Main UI Problems

## 3.1 No information priority

The most important issue is that the page does not distinguish between:
- critical sectors
- moderately relevant sectors
- neutral sectors
- irrelevant sectors

Everything is rendered in the same visual language.

For live use, this is wrong.
The screen should force an order of attention.

Current effect:
- the operator must manually hunt for useful signals
- the UI does not guide attention

## 3.2 Color usage destroys meaning

`Trend.tsx` assigns sector colors from a long rotating palette:
- red
- blue
- green
- orange
- purple
- cyan
- pink

This is appropriate for category separation in a chart legend.
It is not appropriate for a high-density operational screen.

Why it fails:
- color is being used for identity, not meaning
- but the screen density makes users interpret color as meaning anyway
- strong colors everywhere remove the ability to highlight true urgency

In an operator UI, color should mean things such as:
- strong positive move
- strong negative move
- warning
- blocked
- neutral

Current color behavior makes those semantics impossible.

## 3.3 Too many zero-information items are promoted

The capture shows a large number of sectors with `+0%`.

Those entries are not helping the operator.
They dilute attention and reduce contrast with the few items that may actually matter.

In a fast market screen:
- low-change sectors should be collapsed
- quiet sectors should move to a secondary layer
- the main screen should emphasize deviation, anomaly, momentum, catalyst, and actionability

## 3.4 No scan path

Good operational screens create a reading path such as:

1. market state summary
2. urgent movers
3. catalysts
4. trade candidates
5. blocked/incident queue

The current captured page has no such path.

It behaves like a large wall of equal-level tokens.
That forces the user to inspect manually instead of react quickly.

## 3.5 No action linkage

Even if a sector is moving, the page does not connect that movement to:
- representative stocks
- event/news/disclosure reason
- signal status
- risk block status
- order/execution status

That means the screen is not action-oriented.

For auto-trading operations, every important movement should be traceable to:
- why it moved
- whether the engine reacted
- whether trade is allowed
- what happened next

## 3.6 The page is data-rich but operator-poor

`Trend.tsx` contains:
- sector filters
- cumulative line chart
- sector ranking table
- expandable stock rows

This is useful analytical tooling.
It is not enough for an operator who needs to understand the live market state fast.

The current page is better for browsing than for triage.

---

## 4. Why The Current Code Produces This Result

## 4.1 `Trend.tsx` is optimized for exhaustive listing

Key behaviors in [Trend.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Trend.tsx):
- loads all sectors
- defaults to top 10 in the line chart
- still renders the full sector filter grid
- exposes all sectors through equal-size labels
- uses a long identity color palette

This design assumes:
- more visible sectors is better
- selection is the main user action

For an operator-facing surface, the opposite is usually true:
- fewer, more important sectors should be promoted first
- the default view should already be highly curated

## 4.2 `Dashboard.tsx` is summary-heavy rather than decision-heavy

[Dashboard.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Dashboard.tsx) prioritizes:
- total value
- daily pnl
- return
- MDD
- position count
- portfolio composition
- signal distribution

This answers:
- how the system is doing overall

It does not answer quickly enough:
- what is changing right now
- what needs attention now
- what the engine is about to do
- what the operator must validate or stop

So even outside the captured `Trend` page, the product’s main UI still leans toward summary dashboards rather than operational control.

---

## 5. What The UI Should Do Instead

The system should be reorganized around a live operator workflow.

Recommended primary reading flow:

1. market state
   - risk-on / risk-off
   - number of active movers
   - number of significant catalysts
   - stale feed or broker incident status

2. urgent opportunities and incidents
   - top movers
   - top negative moves
   - new catalysts
   - blocked trades
   - failed or unknown orders

3. actionable candidates
   - eligible
   - blocked
   - executed
   - watching

4. drilldown
   - selected sector or symbol
   - catalyst
   - liquidity
   - risk checks
   - order state

This is the correct flow for the product goal.

---

## 6. Concrete Redesign For The Current Trend Screen

Replace the current chip wall with a three-layer layout.

## 6.1 Top strip: market summary

Show only:
- active sectors count
- accelerated sectors count
- sectors with fresh catalyst
- sectors blocked by risk
- stale data / broker / kill switch indicators

This creates an immediate state read.

## 6.2 Main left: top sectors only

Show 5 to 10 sector cards max.
Each card should contain:
- sector name
- move magnitude
- acceleration
- top 3 stocks
- event count
- signal count
- blocked/eligible state

This replaces equal-weight chips with ranked objects.

## 6.3 Main right: incident and action queue

Show:
- new catalyst queue
- blocked candidates
- execution issues
- stale feed warnings

This creates an operator action surface.

## 6.4 Lower panel: selected sector details

When a sector is selected, show:
- sector trend
- top symbols
- why it moved
- current signal states
- risk status
- latest order/execution records

That keeps depth without overwhelming the main view.

---

## 7. Visual System Corrections

The current UI needs stricter visual semantics.

Recommended rules:

- Reserve strong green/red for meaningful price direction only.
- Use one muted neutral palette for quiet categories.
- Use amber for warning and cyan/blue for informational status.
- Remove rainbow identity colors from dense operational layouts.
- Use size, spacing, and rank to show priority before using color.
- Hide or collapse `0%` and low-signal entries by default.

This will improve usability much more than cosmetic restyling.

---

## 8. Bottom Line

The capture confirms the earlier concern:
- the UI currently exposes a lot of data
- but it does not structure that data for rapid decision-making

The most urgent UI issue is not component quality.
It is product intent mismatch.

The current UI is still built like:
- "show the available analysis"

It should be rebuilt toward:
- "show what matters now, what is actionable, what is blocked, and what requires operator attention"

That should be the guiding rule for the next UI redesign.
