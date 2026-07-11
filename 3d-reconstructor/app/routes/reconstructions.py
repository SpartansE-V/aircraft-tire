from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..schemas import ReconstructionRequest
from ..services.mast3r_reconstructor import Mast3rService

router = APIRouter(prefix="/reconstructions", tags=["reconstructions"])


def _get_service(request: Request) -> Mast3rService:
    return request.app.state.reconstruction_service


def _job_run_dir(service: Mast3rService, job_id: str) -> Path:
    record = service.store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    run_dir = Path(record.paths.run_dir).resolve()
    if not run_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run directory not found; the job may not have produced any output.",
        )
    return run_dir


@router.get("")
def list_reconstructions(request: Request) -> list[dict[str, object]]:
    service = _get_service(request)
    return service.store.list_jobs()


@router.get("/{job_id}")
def get_reconstruction(job_id: str, request: Request) -> dict[str, object]:
    service = _get_service(request)
    payload = service.store.get_job_payload(job_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return payload


@router.get("/{job_id}/model.glb")
def get_reconstruction_glb(job_id: str, request: Request) -> FileResponse:
    service = _get_service(request)
    record = service.store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    model_glb = Path(record.paths.model_glb)
    if not model_glb.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GLB available; the reconstruction may not have completed.",
        )
    return FileResponse(model_glb, filename=f"reconstruction-{job_id}.glb", media_type="model/gltf-binary")


@router.get("/{job_id}/pointmaps")
def get_reconstruction_pointmaps(job_id: str, request: Request) -> FileResponse:
    service = _get_service(request)
    record = service.store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    pointmaps = Path(record.paths.pointmaps)
    if not pointmaps.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No point maps available; the reconstruction may not have completed.",
        )
    return FileResponse(pointmaps, filename=f"pointmaps-{job_id}.npz", media_type="application/octet-stream")


@router.get("/{job_id}/files")
def list_reconstruction_files(job_id: str, request: Request) -> dict[str, object]:
    service = _get_service(request)
    run_dir = _job_run_dir(service, job_id)
    files = [
        {"path": path.relative_to(run_dir).as_posix(), "size": path.stat().st_size}
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    ]
    return {"job_id": job_id, "run_dir": str(run_dir), "files": files}


@router.get("/{job_id}/files/{file_path:path}")
def download_reconstruction_file(job_id: str, file_path: str, request: Request) -> FileResponse:
    service = _get_service(request)
    run_dir = _job_run_dir(service, job_id)

    target = (run_dir / file_path).resolve()
    try:
        target.relative_to(run_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File path must stay inside the run directory."
        ) from exc
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_reconstruction(
    payload: ReconstructionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, object]:
    service = _get_service(request)
    try:
        options = payload.to_options(service.settings)
        job = service.create_job(options)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    background_tasks.add_task(service.run_job, job["job_id"])
    return job
