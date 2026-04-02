# AlphaTrade — Common Commands
# Usage: make test, make build, make up, etc.

.PHONY: test test-unit test-gui test-cov build up down logs backup

# Run unit tests + GUI audit
test: test-unit test-gui

# Run backend unit tests inside Docker container
test-unit:
	docker compose build core-engine 2>&1 | tail -1
	docker compose up -d core-engine 2>&1 | tail -1
	sleep 5
	docker exec alphatrade-core-engine rm -rf /app/tests
	docker cp core-engine/tests alphatrade-core-engine:/app/tests
	docker compose exec core-engine python -m pytest tests/ -x --tb=short -q

# Run Playwright GUI audit against the live dashboard
test-gui:
	docker compose build dashboard 2>&1 | tail -1
	docker compose up -d dashboard 2>&1 | tail -1
	sleep 5
	node scripts/gui_audit.mjs

# Run tests with coverage report
test-cov:
	@docker compose build core-engine --quiet
	@docker compose up -d core-engine --quiet 2>/dev/null
	@sleep 3
	@docker exec alphatrade-core-engine rm -rf /app/tests
	@docker cp core-engine/tests alphatrade-core-engine:/app/tests
	@docker compose exec core-engine python -m pytest tests/ --cov=app --cov-report=term-missing -q

# Build all services
build:
	docker compose build

# Start all services
up:
	docker compose up -d

# Force recreate core-engine + dashboard
deploy:
	docker compose build core-engine dashboard
	docker compose up -d --force-recreate core-engine dashboard

# Stop all services
down:
	docker compose down

# View logs
logs:
	docker compose logs -f core-engine

# Health check
health:
	@curl -sf http://localhost:8000/health | python3 -m json.tool 2>/dev/null || curl -sf http://localhost:8000/health

# Run backup
backup:
	./scripts/backup.sh full

# Kill switch status
status:
	@curl -sf http://localhost:8000/trading/kill-switch/status | python3 -m json.tool 2>/dev/null || echo "Core engine not running"
