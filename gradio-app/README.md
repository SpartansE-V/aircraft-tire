# Tyre 3D Defect Mapping (Gradio + MASt3R)

A single Gradio app that combines the two SpartansE-X capabilities:

- **3D reconstruction** — **MASt3R** (Naver, learning-based), called over HTTP
  (the `3d-reconstructor` service). Robust on low-texture, few-image, and
  rotationally-symmetric scenes where COLMAP fails.
- **Crack / defect detection** — Roboflow YOLO tyre-quality (and tread-depth) models.

…and the key feature: it **projects the 2D detections onto the reconstructed 3D
model**. MASt3R produces a **dense per-pixel 3D point map**, so each detected crack
box maps directly to 3D points, which are highlighted in red on the model.

## How the projection works

1. Detect defect boxes in each 2D image (Roboflow).
2. Reconstruct dense 3D with MASt3R (via the reconstructor API), which returns a
   per-image point map (a 3D point for every pixel) + confidence + camera pose,
   plus the exact resize/crop transform from original pixels to point-map indices.
3. For each image, map each detection box into point-map indices and flag the
   confident 3D points under the box.
4. Write `defects.glb` — flagged points recolored red, everything else keeps its
   reconstructed color — and show it in `gr.Model3D` (GLB renders natively).

Because MASt3R gives dense per-pixel 3D, the highlight is dense and exact — no
sparse-track guesswork.

## Project layout

```text
gradio-app/
├── app.py                     # Gradio UI + streaming orchestration
├── pipeline/
│   ├── config.py              # env-backed config
│   ├── reconstructor_client.py # HTTP client for the MASt3R service
│   ├── detector.py             # Roboflow inference + Detection dataclass
│   ├── projector.py            # dense box->pointmap projection + colored GLB  ← core
│   ├── glb.py                  # trimesh GLB point-cloud writer
│   ├── annotate.py             # draw detection boxes on images
│   └── runner.py               # detect → reconstruct → project (streaming generator)
├── tests/                      # projector (synthetic pointmaps) + client (mock transport)
├── Dockerfile / compose.yaml / requirements.txt / .env.example
```

## Run with Docker (single GPU host)

Compose builds both the MASt3R reconstructor (GPU) and this app:

```bash
cd aircraft-tire/gradio-app
cp .env.example .env          # set ROBOFLOW_API_KEY
docker compose up --build -d  # app on http://<host>:7860
```

Needs the NVIDIA Container Toolkit. First build is slow (clones MASt3R + downloads
the ~2 GB checkpoint). CPU-only: see the reconstructor README.

## Run split (app local, reconstructor remote)

Common for deployment: reconstructor on a remote GPU box, app anywhere.

```bash
cd aircraft-tire/gradio-app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ROBOFLOW_API_KEY=your-key
export RECONSTRUCTOR_API_URL=http://<gpu-host>:8000
python app.py                 # http://localhost:7860
```

## Using the app

1. Upload photos (a handful of overlapping shots, or a turntable sequence — even 2
   views can work with MASt3R).
2. Pick a detection model + confidence.
3. Paste a Roboflow key if not set in the environment.
4. (Optional) open **Reconstruction options** for input size (512/224), min
   confidence, and optimization level.
5. Click **Run**. Progress + the reconstructor's MASt3R logs stream in; annotated
   2D detections, the 3D model (defects in red), a summary, and a downloadable
   `.glb` appear as they are ready.

Without an API key the app still reconstructs the 3D model, just without the defect overlay.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `RECONSTRUCTOR_API_URL` | `http://localhost:8000` | MASt3R reconstructor base URL. |
| `RECONSTRUCTOR_JOB_TIMEOUT` | `1800` | Max seconds to wait for a job. |
| `ROBOFLOW_API_KEY` | _(empty)_ | Roboflow key (also accepts `ROBOFLOW__API_KEY`). |
| `CRACK_MODEL_ID` / `TREAD_MODEL_ID` | tyre models | Detection model ids. |
| `MAST3R_IMAGE_SIZE` / `MAST3R_MIN_CONF_THR` / `MAST3R_OPTIM_LEVEL` | 512 / 1.5 / refine+depth | UI defaults. |
| `GRADIO_SERVER_PORT` | `7860` | Gradio port. |

## Tests

```bash
pip install pytest
pytest    # dense projector (synthetic point maps) + reconstructor client (mock transport)
```

## Notes & license

- Reconstruction quality/latency depend on the MASt3R host (GPU strongly preferred).
- **License:** MASt3R / DUSt3R / CroCo are **CC BY-NC-SA 4.0 (non-commercial)** —
  review before any commercial use.
