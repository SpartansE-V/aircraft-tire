.PHONY: install run test lint format-check type-check compile check docker-build docker-up docker-down docker-logs

install:
	uv sync

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port $${PORT:-8000}

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
	docker compose -f ../docker-compose.yml up --build -d

docker-down:
	docker compose -f ../docker-compose.yml down

docker-logs:
	docker compose -f ../docker-compose.yml logs -f api
