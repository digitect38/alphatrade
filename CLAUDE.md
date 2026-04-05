# AlphaTrade — Claude Code Instructions

## Mandatory: Docker Deploy After Code Changes

Every time you modify source code (frontend or backend), you MUST automatically run the following steps without waiting for user instruction:

1. Type check (`npx tsc --noEmit` for frontend, `python3 -m py_compile` for backend)
2. `docker compose build <changed-services>` (dashboard, core-engine, or both)
3. `docker compose up -d <changed-services>`
4. Verify container is running and healthy

This is a BLOCKING REQUIREMENT — never skip it. If you forget, the user's running application won't reflect the changes, making all testing meaningless.

## Project Structure

- `core-engine/` — Python/FastAPI backend
- `dashboard/` — React/TypeScript frontend (Vite)
- `docker-compose.yml` — 9 services (timescaledb, redis, core-engine, dashboard, n8n, grafana, prometheus, cloudflared, nginx)

## Key Services

- `dashboard` — port 3000, Nginx serving Vite build
- `core-engine` — port 8000, FastAPI with TimescaleDB + Redis

## Mandatory: Update Spec Documentation

When adding or changing user-facing features, you MUST update the relevant documentation:

- `docs/status-and-next-plan-v1.4.md` — version history table and feature tables
- `docs/asset-detail-ui-spec-v1.md` — for chart/AssetDetail changes

Do this in the same commit as the code change or immediately after.

## Language

- Respond in the same language the user uses (Korean or English)
