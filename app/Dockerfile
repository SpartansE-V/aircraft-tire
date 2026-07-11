FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

ARG OPENAI_API_KEY

WORKDIR /app

# opencv-python (pulled in by inference-sdk) needs libGL/glib at import time,
# which python:3.12-slim doesn't ship.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra ai

# app/ carries the code plus the RUL endpoint's runtime inputs — scoring thresholds
# (app/tire_rul/config/) and the fitted population prior (app/tire_rul/artifacts/mixedlm_covariance.pkl,
# 386 B). Training data and heavy research artifacts are excluded via .dockerignore.
COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["/bin/sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
