# COLMAP Reconstruction API

This folder contains a FastAPI server that wraps the `colmap` CLI and exposes reconstruction jobs over HTTP.

## What it does

- Checks whether `colmap` is installed and reachable.
- Accepts reconstruction requests for an image folder inside a configured workspace.
- Runs the COLMAP sparse pipeline by default.
- Optionally runs dense reconstruction steps as part of the same job.
- Keeps in-memory job status, command history, and logs for quick inspection.

## Project layout

```text
3d-reconstructor/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── domain.py
│   ├── job_store.py
│   ├── routes/
│   ├── schemas.py
│   └── services/
├── compose.yaml
├── Dockerfile
├── requirements.txt
└── tests/
```

## Local setup

1. Create a virtual environment.
2. Install the Python dependencies.
3. Install COLMAP on your machine and make sure the `colmap` command is available in `PATH`.

```bash
cd /Users/nhannguyen/Documents/Projects/SpartansE-X/3d-reconstructor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

These are optional. Defaults are shown below.

```bash
export COLMAP_BINARY=colmap
export COLMAP_WORKSPACE_ROOT=/Users/nhannguyen/Documents/Projects/SpartansE-X/3d-reconstructor/workspace
export COLMAP_IMAGES_ROOT=/Users/nhannguyen/Documents/Projects/SpartansE-X/3d-reconstructor/workspace/images
export COLMAP_OUTPUTS_ROOT=/Users/nhannguyen/Documents/Projects/SpartansE-X/3d-reconstructor/workspace/runs
export COLMAP_DEFAULT_CAMERA_MODEL=SIMPLE_RADIAL
export COLMAP_DEFAULT_MATCHER=exhaustive
```

The server only accepts image directories that resolve under `COLMAP_WORKSPACE_ROOT`.

## Run locally

```bash
cd /Users/nhannguyen/Documents/Projects/SpartansE-X/3d-reconstructor
uvicorn app.main:app --reload
```

## Run with Docker

The container expects your input images and output artifacts to live under `./workspace`, which is mounted into the container at `/app/workspace`.

1. Copy the env template if you want to override defaults.

```bash
cd /Users/nhannguyen/Documents/Projects/SpartansE-X/3d-reconstructor
cp .env.example .env
```

On Apple Silicon or any non-amd64 Docker host, the default configuration pins the image to `linux/amd64` because the official COLMAP container may not resolve to a native ARM build. If you have a native-compatible replacement image later, you can change `DOCKER_PLATFORM` in `.env`.

2. Start the CPU-safe deployment.

```bash
docker compose up --build -d api
```

3. If your Docker host has NVIDIA GPU support and you want GPU-accelerated COLMAP, start the GPU profile instead.

```bash
docker compose --profile gpu up --build -d api-gpu
```

4. Check the API.

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/colmap
```

5. Stop the deployment.

```bash
docker compose down
```

## Example request

### Option A: upload images first

Send files from an outside client:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/uploads/images \
  -F "project_name=my-scene" \
  -F "files=@/absolute/path/to/image-01.jpg" \
  -F "files=@/absolute/path/to/image-02.jpg"
```

The response includes an `image_dir` like `images/my-scene`.
The response also includes a server-generated `project_uuid`, and the uploaded files are stored under `images/<project_uuid>`.

### Option B: reference an existing local folder

Put your images under `workspace/images/my-scene/`.

### Start reconstruction

Then call:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/reconstructions \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "my-scene",
    "image_dir": "images/my-scene",
    "dense": true,
    "matcher": "exhaustive",
    "use_gpu": false
  }'
```

## Endpoints

- `GET /api/v1/health`
- `GET /api/v1/colmap`
- `POST /api/v1/uploads/images`
- `GET /api/v1/reconstructions`
- `GET /api/v1/reconstructions/{job_id}`
- `POST /api/v1/reconstructions`

## Deployment notes

- Job state is stored in memory, so restarting the API clears the job list.
- Keep this service to a single container instance and a single Uvicorn worker unless you replace the in-memory job store with Redis, Postgres, or another shared backend.
- The Docker deployment is the easiest way to ship the API because the image already contains COLMAP.
