.PHONY: install test test-unit test-integration test-live lint fmt \
        serve mcp docker-build docker-up demo clean

# ── Setup ──────────────────────────────────────────────────────────────────

PYTHON ?= python3.11

install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip -q
	.venv/bin/pip install -e ".[dev]" -q

# ── Testing ────────────────────────────────────────────────────────────────

test: test-unit test-integration

test-unit:
	.venv/bin/python3.11 -m pytest -m unit -v

test-integration:
	.venv/bin/python3.11 -m pytest -m integration -v

test-live:
	LOGSENSE_LIVE_TESTS=1 .venv/bin/python3.11 -m pytest -m live -v

# ── Code quality ───────────────────────────────────────────────────────────

lint:
	ruff check logsense tests

fmt:
	ruff format logsense tests

# ── Local run ──────────────────────────────────────────────────────────────

serve:
	uvicorn logsense.api.app:app --host 0.0.0.0 --port 8000 --reload

mcp:
	python -m logsense.mcp_server.server

# ── Docker ─────────────────────────────────────────────────────────────────

docker-build:
	docker build -t logsense:latest .

docker-up:
	docker compose up --build -d

docker-logs:
	docker compose logs -f

docker-down:
	docker compose down -v

# ── Demo ───────────────────────────────────────────────────────────────────

demo:
	@echo "Running end-to-end LogSense demo..."
	bash scripts/demo.sh

# ── Housekeeping ───────────────────────────────────────────────────────────

clean:
	rm -f logsense.db
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -f coverage.xml .coverage
