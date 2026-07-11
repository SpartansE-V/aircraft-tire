# MASt3R reconstruction service — GPU image.
# MASt3R runs on CPU too (no CUDA), but is much slower; deploy on a CUDA GPU host.
FROM pytorch/pytorch:2.1.2-cuda11.8-cudnn8-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    MAST3R_HOME=/opt/mast3r \
    MAST3R_WORKSPACE_ROOT=/app/workspace \
    MAST3R_IMAGES_ROOT=/app/workspace/images \
    MAST3R_OUTPUTS_ROOT=/app/workspace/runs \
    MAST3R_DEVICE=auto \
    HF_HOME=/opt/hf-cache

# System libs: git (clone), wget (checkpoint), libgl/glib (opencv/trimesh).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git wget ca-certificates libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Clone MASt3R with DUSt3R + CroCo submodules.
RUN git clone --recursive https://github.com/naver/mast3r.git ${MAST3R_HOME}

# Python deps. Torch/torchvision already ship in the base image; the repo
# requirements add roma, opencv, scipy, einops, trimesh, huggingface-hub, etc.
# CroCo's optional CUDA RoPE kernels are NOT compiled — MASt3R falls back to a
# pure-pytorch RoPE, which is correct (just a little slower).
RUN pip install --upgrade pip && \
    pip install -r ${MAST3R_HOME}/dust3r/requirements.txt && \
    pip install -r ${MAST3R_HOME}/requirements.txt && \
    pip install pillow-heif

# Pre-download the metric checkpoint so first inference is fast / offline-capable.
RUN mkdir -p ${MAST3R_HOME}/checkpoints && \
    wget -q https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth \
      -O ${MAST3R_HOME}/checkpoints/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth
ENV MAST3R_MODEL_NAME=${MAST3R_HOME}/checkpoints/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth

# Make mast3r / dust3r / croco importable.
ENV PYTHONPATH=${MAST3R_HOME}:${MAST3R_HOME}/dust3r:${MAST3R_HOME}/dust3r/croco

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY README.md ./README.md

RUN mkdir -p /app/workspace/runs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
