FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# opencv-python (pulled in by inference-sdk) needs libGL/glib at import time,
# which python:3.12-slim doesn't ship.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# Runtime inputs for the RUL AI endpoint: scoring thresholds + the fitted population prior
# (386 B). Training data and heavy research artifacts are excluded via .dockerignore.
COPY config ./config
COPY artifacts/mixedlm_covariance.pkl ./artifacts/mixedlm_covariance.pkl

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["/bin/sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
