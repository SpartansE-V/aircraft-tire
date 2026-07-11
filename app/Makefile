.PHONY: install install-ai run run-api run-web ui data enrich-scans scans logs train test lint format-check type-check compile check docker-build docker-up docker-down docker-logs

WEB_DIR := ../web

# --- Backend (API) ---
install:
	uv sync --extra ai

run:
	@$(MAKE) run-api & api_pid=$$!; \
	trap 'kill $$api_pid 2>/dev/null || true' EXIT INT TERM; \
	$(MAKE) run-web

run-api:
	uv run --extra ai uvicorn app.main:app --app-dir .. --host 0.0.0.0 --port $${PORT:-8000}

run-web:
	npm run dev --prefix $(WEB_DIR)

# --- AI pipeline (needs the full ML stack: `make install-ai`) ---
install-ai:
	uv sync --extra ai

ui:
	uv run streamlit run app/tire_rul/app.py

data:
	uv run python -m app.tire_rul.generate_data

# Idempotent with the default seed; rewrites scan columns on tires.parquet.
# Needs ../assets/mock-tyres/release/*/metadata.json (JSON only, not the PNGs).
enrich-scans:
	PYTHONPATH=.. uv run python -m app.tire_rul.enrich_tire_assets

scans:
	uv run python -m app.tire_rul.generate_scans

logs:
	uv run python -m app.tire_rul.generate_defect_logs

train:
	uv run python -m app.tire_rul.train

# --- Quality gates ---
# The suite lives at <repo>/tests (rootdir is the repo root, per ../pytest.ini). Point pytest
# at it explicitly: `testpaths` only kicks in when cwd == rootdir, and we run from app/.
test:
	uv run pytest -q ../tests

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

type-check:
	uv run mypy app

compile:
	uv run python -m compileall app

check: format-check lint type-check test compile

docker-build:
	docker build -t wear-severity-api .

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f api
