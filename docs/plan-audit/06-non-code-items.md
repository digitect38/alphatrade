# Non-Code And Hard-To-Verify Plan Items

These plan sections are not fully auditable from repository code alone.

## Items marked `N/A`

| Plan section | Status | Reason |
|---|---|---|
| Development schedule and week-by-week phase timing | N/A | Timing cannot be validated from repository state alone. |
| Cost analysis | N/A | Financial assumptions are documentation-level, not code-level. |
| Tool decision matrix | N/A | This is a planning artifact, not an implementation artifact. |
| MacBook deployment suitability | N/A | Partially inferable, but not objectively verifiable from repo contents. |
| Operational policies such as “final trade decision must come from ensemble” | Partial | The code contains ensemble and webhook flows, but intent/policy enforcement across all paths is not fully provable from a static audit. |

## Recommended next actions

| Priority | Action |
|---|---|
| High | Export and commit the full n8n workflow set described in the plan. |
| High | Replace placeholder Grafana JSON files with real dashboard definitions. |
| Medium | Decide whether the planned `TradingView -> n8n -> core-engine` path is still required; current repo already supports direct webhook ingestion. |
| Medium | Either implement WebSocket updates or update the plan to reflect a REST/polling dashboard architecture. |
| Medium | Add a short “implemented vs planned” matrix to `docs/` so the repo state and planning document stop drifting apart. |
