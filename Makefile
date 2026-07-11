.PHONY: install run test lint format-check type-check compile check docker-build

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
