# Trend Redesign Spec

Date:
- 2026-03-31

Scope:
- full redesign of `dashboard/src/pages/Trend.tsx`
- replacement of the current sector-chip and chart-first layout
- new role for the page as `Market Intel`, not a generic sector browser

References:
- [Trend.tsx](/Users/woosj/DevelopMac/alpha_trade/dashboard/src/pages/Trend.tsx)
- [ui-capture-review-2026-03-30.md](/Users/woosj/DevelopMac/alpha_trade/docs/ui-capture-review-2026-03-30.md)
- [command-center-ui-spec-v1.md](/Users/woosj/DevelopMac/alpha_trade/docs/command-center-ui-spec-v1.md)

Primary goal:
- turn the current horrible `추세` page into a page that helps the operator understand sector-level market structure quickly

Short answer:
- stop rendering all sectors as equal chips
- stop making the chart the main event
- replace the page with ranked sector intelligence, catalyst context, and sector drilldown

---

## 1. Product Role

The current `Trend` page has the wrong job.

Right now it behaves like:
- a sector catalog
- a multi-line chart playground
- a broad ranking table

That is not the right role for this product.

The new role should be:
- sector-level market intelligence
- a bridge between market movement and trading action

This page should answer:

1. Which sectors are actually moving?
2. Which sectors are accelerating?
3. Which sectors have fresh catalysts?
4. Which sectors contain actionable candidates?
5. Which sectors are noisy but not useful?

If the page cannot answer those, it should not exist in its current form.

---

## 2. Why The Current Page Fails

The current page fails for structural reasons:

- it exposes too many sectors at once
- it gives too much space to low-signal sectors
- it uses identity colors where meaning colors are needed
- it forces users to browse instead of triage
- it separates sector movement from catalyst, risk, and actionability

The main anti-pattern is:
- `show everything, let the user sort it out`

The redesign principle must be:
- `show the most meaningful sectors first, and explain why they matter`

---

## 3. New Page Name And Role

Recommended rename:
- `Trend` -> `Market Intel`

Reason:
- `Trend` sounds like a chart page
- the new page should be broader than trend lines
- it should combine trend, catalyst, market breadth, and candidate relevance

If the route name is kept temporarily, the page still needs to be redesigned to act like `Market Intel`.

---

## 4. New Layout

Recommended desktop layout:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ PAGE TITLE: Market Intel                                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ TOP SUMMARY                                                                 │
│ [Active Sectors] [Accelerating] [Catalyst Sectors] [Tradeable Sectors]      │
├───────────────────────────────────────────────┬──────────────────────────────┤
│ PRIORITY SECTORS                              │ SECTOR ALERTS                │
│ ranked sector cards                           │ fresh catalysts              │
│ top 6-10 only                                 │ blocked sectors              │
│ each card shows actionability                 │ unusual breadth              │
├───────────────────────────────────────────────┴──────────────────────────────┤
│ MARKET BREADTH / REGIME STRIP                                                │
│ risk-on, risk-off, sector participation, positive vs negative breadth        │
├───────────────────────────────────────────────┬──────────────────────────────┤
│ SELECTED SECTOR DETAIL                        │ SELECTED SECTOR CANDIDATES   │
│ mini trend                                    │ top symbols in sector        │
│ cumulative move                               │ move / catalyst / signal     │
│ avg change                                    │ eligible / blocked           │
│ catalyst summary                              │ execution state              │
├───────────────────────────────────────────────┴──────────────────────────────┤
│ QUIET / SECONDARY SECTORS (collapsed by default)                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

This should replace both:
- the giant chip wall
- the chart-first emphasis

---

## 5. Top Summary Row

The first row must summarize sector state, not list sector names.

Cards:
- `Active Sectors`
- `Accelerating Sectors`
- `Catalyst Sectors`
- `Tradeable Sectors`

Definitions:
- `Active Sectors`: sectors with meaningful average move or breadth deviation
- `Accelerating Sectors`: sectors whose move is strengthening over recent interval
- `Catalyst Sectors`: sectors with fresh news/disclosure/event concentration
- `Tradeable Sectors`: sectors that contain at least one eligible symbol

Rules:
- no chart here
- no long labels
- no sector chip dump

---

## 6. Priority Sectors Panel

This becomes the main body of the page.

Show:
- only top 6 to 10 sectors
- ranked by sector priority score

Each sector card must show:
- sector name
- average move
- cumulative move
- stock count
- positive vs negative breadth
- catalyst badge count
- eligible symbol count
- blocked symbol count

Each card should also show a short reason line, for example:
- `Breadth strong, 2 catalyst symbols, 1 eligible`
- `Move strong but blocked by session rule`

This is the center of the page.

---

## 7. Sector Alerts Panel

This replaces useless wide color noise with explicit signal panels.

Contents:
- fresh sector catalysts
- sectors with unusual breadth
- sectors with strong move but no tradeable candidates
- sectors with blocked opportunities

Example alert items:
- `Semiconductors: 3 catalyst symbols in 15m`
- `Defense: strong breadth but all candidates blocked`
- `Biotech: disclosure-driven move with no confirmation`

This panel should not be large.
It is a fast-scan side rail.

---

## 8. Market Breadth Strip

The page needs a compact regime read.

Show:
- positive sectors count
- negative sectors count
- strongest breadth sectors
- weakest breadth sectors
- current market tone

Possible tones:
- `risk-on`
- `mixed`
- `risk-off`

This is much more useful than a giant multi-line sector chart as the default view.

---

## 9. Selected Sector Detail

The lower section becomes context-rich drilldown.

For the selected sector, show:

- mini cumulative trend chart
- latest average move
- breadth ratio
- recent catalysts
- summary of why the sector is active

This is where a chart belongs.
The chart should support explanation, not dominate the page.

---

## 10. Selected Sector Candidates

The selected sector must connect to actual tradable symbols.

Show top symbols in that sector with:
- stock code and name
- move percent
- volume context
- catalyst reason
- signal state
- eligibility state
- latest order state

States:
- `eligible`
- `watching`
- `blocked`
- `executed`

This is the most important addition.
Without it, the page remains detached from trading action.

---

## 11. What Must Be Removed

These should not survive the redesign as primary UI:

- full sector chip wall
- rainbow per-sector identity colors
- showing every sector at equal weight
- default visibility for `0%` sectors
- chart as the first and largest object
- sector browsing as the main interaction model

If any of these remain dominant, the redesign has failed.

---

## 12. Visual Rules

Color rules:
- red: strong positive move
- blue: strong negative move
- amber: blocked or caution
- green: eligible / constructive
- gray: quiet / secondary

Do not:
- assign each sector its own bright color
- use high-saturation chips in dense collections

Layout rules:
- cards before tables
- ranking before browsing
- explanation before raw detail
- collapsed secondary information by default

---

## 13. Interaction Model

Default experience:

1. operator opens page
2. sees top sector state summary
3. scans ranked priority sectors
4. clicks one sector
5. sees candidate symbols and catalyst details

Not acceptable:

1. operator opens page
2. sees 100+ chips
3. manually guesses what matters

---

## 14. Data Requirements

The current endpoints are not enough for the best version of this page.

Preferred data model:

- sector priority score
- sector breadth
- sector catalyst count
- sector candidate counts by state
- top symbols per sector
- blocked reasons summary per sector

Suggested backend endpoint shape:

- `GET /market-intel/sectors`
  - top sectors
  - breadth
  - catalyst counts
  - candidate counts
- `GET /market-intel/sectors/{sector}`
  - detail
  - top symbols
  - event summary
  - execution summary

Short-term fallback:
- derive from existing `index` and market/candidate endpoints

---

## 15. Migration From Current `Trend.tsx`

Current sections:
- chart tab
- ranking tab
- sector filter chip grid
- cumulative multi-line chart
- ranking table with expandable rows

New sections:
- summary cards
- priority sector cards
- sector alerts rail
- market breadth strip
- selected sector detail
- selected sector candidates

Migration decision:
- do not preserve current structure
- rebuild the page from scratch

---

## 16. Implementation Order

Recommended order:

1. remove chip wall
2. replace tab layout with single ranked intelligence layout
3. add top summary cards
4. add priority sector cards
5. add selected sector detail
6. add selected sector candidates
7. move quiet sectors into collapsed secondary section

---

## 17. Success Criteria

The redesign is successful if:

- a user can identify the top 5 important sectors in under 10 seconds
- quiet sectors do not dominate the screen
- sector movement is connected to actual symbols and action states
- the page explains why a sector matters
- the page supports triage, not browsing

---

## 18. Bottom Line

The current `추세` UI is horrible because it treats visibility as value.

The redesigned page must treat:
- priority
- actionability
- explanation

as the core values instead.
