Build and deploy AlphaTrade services to Docker.

Arguments (optional): dashboard, core-engine, or both (default: both)

Steps:
1. Type check frontend: `cd dashboard && npx tsc --noEmit`
2. Compile check backend: `cd core-engine && python3 -m py_compile app/main.py`
3. Build: `docker compose build $ARGUMENTS`
4. Deploy: `docker compose up -d $ARGUMENTS`
5. Verify health: `curl -s http://localhost:8000/health`
6. Run QA: `cd dashboard && node scripts/qa-full.mjs`

Report build time, deploy status, health check, and QA results.
