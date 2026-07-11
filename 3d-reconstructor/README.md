# MASt3R Reconstruction API

FastAPI service that wraps **MASt3R** (Naver, built on DUSt3R + CroCo) and exposes
image-to-3D reconstruction jobs over HTTP. Learning-based, so it reconstructs
low-texture, few-image, and rotationally-symmetric scenes where classic SfM
(COLMAP) fails to find an initial pair.

> Replaces the previous COLMAP engine. Same job/upload API shape; outputs are now
> **GLB** + dense **point maps** instead of a COLMAP sparse model + PLY.

## What it does

- Accepts image uploads under a workspace (`POST /uploads/images`).
- Runs MASt3R inference + sparse global alignment for a project.
- Produces per run:
  - `model.glb` — colored, confidence-masked point cloud (for viewing/download).
  - `pointmaps.npz` — per-image dense 3D point map + colors + confidence + camera
    pose/intrinsics + the resize/crop transform (used to project 2D detections into 3D).
- Keeps in-memory job status, logs, and quality metrics.

## Endpoints

- `GET  /api/v1/health`
- `GET  /api/v1/runtime`  — torch/device/model info
- `POST /api/v1/uploads/images`
- `POST /api/v1/reconstructions`  — body: `{project_id, image_size?, min_conf_thr?, optim_level?, scene_graph?, shared_intrinsics?}`
- `GET  /api/v1/reconstructions` / `/{job_id}`
- `GET  /api/v1/reconstructions/{job_id}/model.glb`
- `GET  /api/v1/reconstructions/{job_id}/pointmaps`
- `GET  /api/v1/reconstructions/{job_id}/files` / `/files/{path}`

## Deploy (GPU recommended)

MASt3R runs on CPU too but is far slower; deploy on a **CUDA GPU host** with the
NVIDIA Container Toolkit installed. The image is built on
`pytorch/pytorch:2.1.2-cuda11.8-cudnn8-runtime`, clones `naver/mast3r --recursive`
(DUSt3R + CroCo submodules), installs deps, and pre-downloads the metric checkpoint.

```bash
cd aircraft-tire/3d-reconstructor
docker compose up --build -d          # serves http://<host>:8000
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/runtime     # shows resolved device (cuda/cpu)
```

The build downloads the checkpoint (~2 GB) and clones the repos, so the first
build is slow. CroCo's optional CUDA RoPE kernels are **not** compiled — MASt3R
falls back to a correct pure-pytorch RoPE.

CPU-only (no GPU host): remove the `deploy.resources` block in `compose.yaml` and
set `MAST3R_DEVICE=cpu`. Expect minutes per small scene.

## Configuration

See `.env.example`. Key vars: `MAST3R_MODEL_NAME`, `MAST3R_DEVICE` (auto/cuda/cpu),
`MAST3R_IMAGE_SIZE` (512/224), `MAST3R_OPTIM_LEVEL` (coarse/refine/refine+depth),
`MAST3R_MIN_CONF_THR`.

## Notes & license

- Job state is in-memory; a restart clears the job list. Keep to a single worker.
- **License:** MASt3R / DUSt3R / CroCo are **CC BY-NC-SA 4.0 (non-commercial)**.
  Fine for research/hackathon use; review before any commercial deployment.
