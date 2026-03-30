# Non-Code and Hard-to-Verify Items (Gemini Evaluation)

## Item Verification

| Plan Section | Status | Evaluation |
|---|---|---|
| Development Schedule | N/A | Timeline cannot be verified from the codebase. |
| Cost Analysis | N/A | Financial estimates are purely planning-level. |
| MacBook Deployment | Match | The project is configured for lightweight, Docker-based self-hosting on macOS. |
| Hybrid Hybrid Strategy | Partial | "Core Python + No-Code" hybrid is implemented, but the "No-Code" (n8n) part is under-utilized compared to the plan. |

## Recommended Next Actions (Gemini Priority)

| Priority | Action | Reason |
|---|---|---|
| **High** | Expand n8n workflow set | 9/10 planned workflows are missing. The repo is currently a "Python-heavy" system rather than the planned "Hybrid" system. |
| **High** | Implement WebSocket | Real-time updates are a core plan requirement for the dashboard. |
| **Medium** | Re-evaluate Sentiment Routing | Currently in core-engine; consider moving it to n8n as per the plan to allow for more flexible model swapping. |
| **Medium** | Unified API Gateway | Add a top-level reverse proxy (e.g., Nginx, Traefik) to manage access to all containers via a single port/domain. |
