.PHONY: install install-ai run ui data scans logs train test lint format-check type-check compile check docker-build docker-up docker-down docker-logs

# --- Backend (API) ---
install:
	uv sync

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port $${PORT:-8000}

# --- AI pipeline (needs the full ML stack: `make install-ai`) ---
install-ai:
	uv sync --extra ai

ui:
	uv run streamlit run app/rul/app.py

data:
	uv run python -m app.rul.generate_data

scans:
	uv run python -m app.rul.generate_scans

logs:
	uv run python -m app.rul.generate_defect_logs

train:
	uv run python -m app.rul.train

# --- Quality gates ---
test:
	uv run pytest -q

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
