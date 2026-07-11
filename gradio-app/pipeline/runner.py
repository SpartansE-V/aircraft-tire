"""End-to-end orchestration: detect defects, reconstruct in 3D (MASt3R), project.

Exposed as a generator (:func:`run_pipeline`) that yields :class:`PipelineSnapshot`
updates so the UI can stream logs and reveal results stage by stage.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .config import DETECTION_MODELS, Config, get_config
from .detector import Detection, DetectorError, RoboflowDetector
from .projector import ProjectionError, ProjectionResult, project_detections_to_glb
from .reconstructor_client import ReconstructorClient, ReconstructorError

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class PipelineSnapshot:
    stage: str = "idle"
    fraction: float = 0.0
    logs: str = ""
    annotated_images: list[str] = field(default_factory=list)
    detection_rows: list[list[object]] = field(default_factory=list)
    quality: dict[str, object] | None = None
    projection: ProjectionResult | None = None
    model_path: str | None = None
    summary_md: str = ""
    error: str | None = None


def run_pipeline(
    image_paths: Sequence[str],
    *,
    model_key: str,
    api_key: str,
    image_size: int = 512,
    min_conf_thr: float = 1.5,
    optim_level: str = "refine+depth",
    confidence_threshold: float | None = None,
    config: Config | None = None,
) -> Iterator[PipelineSnapshot]:
    cfg = config or get_config()
    snapshot = PipelineSnapshot()
    log_lines: list[str] = []

    def log(message: str) -> PipelineSnapshot:
        log_lines.append(message)
        snapshot.logs = "\n".join(log_lines)
        return snapshot

    def emit(stage: str, fraction: float) -> PipelineSnapshot:
        snapshot.stage = stage
        snapshot.fraction = fraction
        return snapshot

    if not image_paths:
        snapshot.error = "Upload at least two overlapping images to reconstruct a scene."
        yield emit("error", 1.0)
        return

    model = DETECTION_MODELS.get(model_key, DETECTION_MODELS["crack"])
    filter_threshold = (
        confidence_threshold if confidence_threshold is not None else model.filter_confidence_threshold
    )
    resolved_key = (api_key or cfg.roboflow_api_key).strip()

    reconstructor = ReconstructorClient(cfg.reconstructor_api_url, timeout=cfg.reconstructor_job_timeout)
    if not reconstructor.health():
        snapshot.error = (
            f"MASt3R reconstructor API is not reachable at {cfg.reconstructor_api_url}. "
            "Start/deploy it (see README) or set RECONSTRUCTOR_API_URL."
        )
        yield emit("error", 1.0)
        return

    # --- Stage 1: stage uploaded images -------------------------------------
    yield log("Preparing workspace...")
    run_dir = cfg.workspace_root / "runs" / uuid.uuid4().hex
    image_dir = run_dir / "images"
    annotated_dir = run_dir / "annotated"
    image_dir.mkdir(parents=True, exist_ok=True)
    try:
        staged = _stage_images(image_paths, image_dir, cfg.max_upload_bytes)
    except ValueError as exc:
        snapshot.error = str(exc)
        yield emit("error", 1.0)
        return
    yield log(f"Staged {len(staged)} image(s).")
    if len(staged) < 2:
        snapshot.error = "At least two images are required for 3D reconstruction."
        yield emit("error", 1.0)
        return
    yield emit("staged", 0.1)

    # --- Stage 2: detect defects --------------------------------------------
    detections_by_image: dict[str, list[Detection]] = {}
    detection_rows: list[list[object]] = []
    if resolved_key:
        yield log(f"Running '{model.label}' detection ({model.model_id})...")
        try:
            detector = RoboflowDetector(
                api_url=cfg.roboflow_api_url,
                api_key=resolved_key,
                model_id=model.model_id,
                model_confidence_threshold=model.model_confidence_threshold,
                filter_confidence_threshold=filter_threshold,
            )
        except DetectorError as exc:
            snapshot.error = f"Detector setup failed: {exc}"
            yield emit("error", 1.0)
            return

        from .annotate import annotate_image

        total = len(staged)
        for index, path in enumerate(staged, start=1):
            try:
                detections = detector.detect(str(path))
            except DetectorError as exc:
                yield log(f"WARNING: detection failed for {path.name}: {exc}")
                detections = []
            detections_by_image[path.name] = detections
            for det in detections:
                detection_rows.append(
                    [path.name, det.class_name, round(det.confidence, 3),
                     round(det.x, 1), round(det.y, 1), round(det.width, 1), round(det.height, 1)]
                )
            annotated = annotate_image(path, detections, annotated_dir / path.name)
            snapshot.annotated_images.append(str(annotated))
            yield log(f"  {path.name}: {len(detections)} detection(s)")
            yield emit("detecting", 0.1 + 0.2 * (index / total))
        snapshot.detection_rows = detection_rows
        yield log(f"Detection complete: {sum(len(v) for v in detections_by_image.values())} detection(s).")
    else:
        yield log("No Roboflow API key — skipping detection; the 3D model will have no defect overlay.")
        yield emit("detecting", 0.3)

    # --- Stage 3: MASt3R reconstruction (via API) ---------------------------
    yield log("Uploading images to the MASt3R reconstructor...")
    yield emit("reconstructing", 0.35)
    try:
        upload = reconstructor.upload_images(staged)
        project_id = upload.get("project_uuid") or upload.get("project_id")
        if not project_id:
            raise ReconstructorError("Upload response did not include a project id.")
        yield log(f"Uploaded {upload.get('file_count', len(staged))} image(s) (project {project_id}).")

        job = reconstructor.create_job(
            project_id=str(project_id),
            image_size=image_size,
            min_conf_thr=min_conf_thr,
            optim_level=optim_level,
        )
        job_id = job.get("job_id")
        if not job_id:
            raise ReconstructorError("Create response did not include a job_id.")
        yield log(f"Started MASt3R job {job_id}; polling...")

        pointmaps_path, quality = yield from _poll_and_download(
            reconstructor, str(job_id), run_dir, cfg.reconstructor_poll_interval,
            cfg.reconstructor_job_timeout, log, emit,
        )
    except (ReconstructorError, TimeoutError) as exc:
        yield log(f"ERROR: {exc}")
        snapshot.error = f"Reconstruction failed: {exc}"
        yield emit("error", 1.0)
        return

    snapshot.quality = quality
    yield log(
        f"Reconstruction: {quality.get('assessment')} "
        f"({quality.get('n_images')} images, {quality.get('points3D')} points, "
        f"mean conf {quality.get('mean_confidence')})"
    )
    yield emit("reconstructed", 0.85)

    # --- Stage 4: project detections onto the dense point cloud -------------
    yield log("Projecting detections onto the 3D model...")
    output_glb = run_dir / "defects.glb"
    try:
        projection = project_detections_to_glb(
            pointmaps_path=pointmaps_path,
            detections_by_image=detections_by_image,
            output_glb=output_glb,
            defect_color=cfg.defect_color,
        )
    except ProjectionError as exc:
        yield log(f"ERROR: {exc}")
        snapshot.error = f"Projection failed: {exc}"
        yield emit("error", 1.0)
        return

    snapshot.projection = projection
    snapshot.model_path = str(projection.model_path)
    snapshot.summary_md = _build_summary(model.label, quality, projection, resolved_key != "")
    yield log(
        f"Done: {projection.defect_points} of {projection.total_points} 3D points flagged "
        f"across {projection.matched_images} image(s)."
    )
    yield emit("done", 1.0)


def _poll_and_download(client, job_id, run_dir, poll_interval, job_timeout, log, emit):
    """Poll a MASt3R job to completion, then download pointmaps.npz.

    Generator that streams progress and returns ``(pointmaps_path, quality)``.
    """
    seen = 0
    deadline = time.monotonic() + job_timeout
    payload: dict[str, object] = {}
    while True:
        payload = client.get_job(job_id)
        logs = payload.get("logs") or []
        if isinstance(logs, list):
            for line in logs[seen:]:
                yield log(f"[mast3r] {line}")
            seen = len(logs)
        status = str(payload.get("status", "")).lower()
        yield emit(f"reconstructing ({status or 'running'})", 0.6)
        if status == "completed":
            break
        if status == "failed":
            raise ReconstructorError(str(payload.get("error") or "reconstruction job failed."))
        if time.monotonic() > deadline:
            raise TimeoutError(f"job {job_id} did not finish within {job_timeout:.0f}s.")
        time.sleep(poll_interval)

    quality = payload.get("quality") or {}
    if not isinstance(quality, dict):
        quality = {}
    yield log("Downloading dense point maps...")
    pointmaps_path = client.download_pointmaps(job_id, run_dir / "pointmaps.npz")
    return pointmaps_path, quality


def _build_summary(model_label, quality, projection, detection_ran):
    lines = [
        "### Result summary",
        "",
        f"- **Detection model:** {model_label if detection_ran else 'skipped (no API key)'}",
        f"- **Reconstruction:** `{quality.get('assessment', 'unknown')}` "
        f"({quality.get('n_images', 0)} images, mean conf {quality.get('mean_confidence', 0)})",
        f"- **3D points:** {projection.total_points:,}",
        f"- **Defect points (highlighted red):** {projection.defect_points:,}",
    ]
    if projection.per_class:
        lines.append("")
        lines.append("**Defect 3D points by class:**")
        for class_name, count in sorted(projection.per_class.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {class_name}: {count:,}")
    return "\n".join(lines)


def _stage_images(image_paths: Sequence[str], image_dir: Path, max_bytes: int) -> list[Path]:
    staged: list[Path] = []
    used_names: set[str] = set()
    for raw_path in image_paths:
        source = Path(raw_path)
        if not source.is_file():
            raise ValueError(f"Uploaded file not found: {source.name}")
        size = source.stat().st_size
        if size == 0:
            raise ValueError(f"Uploaded file is empty: {source.name}")
        if size > max_bytes:
            raise ValueError(f"{source.name} exceeds the {max_bytes} byte upload limit.")
        safe_name = _normalize_filename(source.name, used_names)
        used_names.add(safe_name)
        destination = image_dir / safe_name
        shutil.copyfile(source, destination)
        staged.append(destination)
    return staged


def _normalize_filename(filename: str, used_names: set[str]) -> str:
    basename = Path(filename).name.strip()
    extension = Path(basename).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{extension or '<none>'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"
        )
    stem = _SAFE_FILENAME.sub("-", Path(basename).stem).strip("-._") or "image"
    candidate = f"{stem}{extension}"
    suffix = 1
    while candidate in used_names:
        candidate = f"{stem}-{suffix}{extension}"
        suffix += 1
    return candidate
