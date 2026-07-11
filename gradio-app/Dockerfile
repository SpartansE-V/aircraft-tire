FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRADIO_WORKSPACE_ROOT=/app/workspace \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

# libgl/libglib are pulled in by opencv (a transitive dep of inference-sdk).
# No heavy 3D deps here: reconstruction (MASt3R) runs in the reconstructor
# service; this app only reads its GLB + point maps (numpy/trimesh).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY app.py ./app.py
COPY pipeline ./pipeline

RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /app/workspace && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/')"

CMD ["python", "app.py"]
