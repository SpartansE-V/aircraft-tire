ARG TARGETPLATFORM=linux/amd64
FROM --platform=${TARGETPLATFORM} colmap/colmap:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    COLMAP_BINARY=colmap \
    COLMAP_WORKSPACE_ROOT=/app/workspace \
    COLMAP_IMAGES_ROOT=/app/workspace/images \
    COLMAP_OUTPUTS_ROOT=/app/workspace/runs

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv "${VIRTUAL_ENV}"

COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY app ./app
COPY README.md ./README.md

RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/workspace/runs && \
    chown -R appuser:appuser /app "${VIRTUAL_ENV}"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
