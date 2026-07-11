# MASt3R reconstruction service — CPU image.
# The deploy target is ECS Fargate (no GPU), so we use CPU-only torch. This keeps
# the image ~4-5 GB (vs ~12 GB for the CUDA base), so Fargate can pull it within
# its ephemeral storage and the CI build fits the runner disk. MASt3R runs on CPU
# via device=auto; deploy on a CUDA GPU host only if you switch to a CUDA torch base.
FROM python:3.12-slim

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

# git/wget for the repo + checkpoint; libgl/glib for opencv/trimesh; build tools
# in case a dependency lacks a wheel.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git wget ca-certificates libgl1 libglib2.0-0 build-essential && \
    rm -rf /var/lib/apt/lists/*

# CPU-only torch (small) BEFORE the repo requirements so their unpinned `torch`
# stays satisfied by this CPU build. The extra-index keeps torch CPU if touched.
RUN pip install --upgrade pip && \
    pip install torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cpu

# Clone MASt3R with DUSt3R + CroCo submodules and install their deps.
# CroCo's optional CUDA RoPE kernels are NOT compiled — pure-pytorch RoPE fallback.
RUN git clone --recursive https://github.com/naver/mast3r.git ${MAST3R_HOME} && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -r ${MAST3R_HOME}/dust3r/requirements.txt \
        -r ${MAST3R_HOME}/requirements.txt \
        pillow-heif

# scipy >= 1.14 removed the `scipy.cluster.hierarchy.distance` re-export that
# MASt3R's sparse_ga (hclust-ward) relies on. Repoint it at the stable
# scipy.spatial.distance.squareform so clustering works on current scipy.
RUN sed -i 's|sch\.distance\.squareform|__import__("scipy.spatial.distance", fromlist=["squareform"]).squareform|g' \
    ${MAST3R_HOME}/mast3r/cloud_opt/sparse_ga.py

# Pre-download the metric checkpoint (baked in -> fast, offline Fargate cold starts).
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
