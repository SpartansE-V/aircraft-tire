from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..schemas import ReconstructionRequest
from ..services.colmap import ColmapService

router = APIRouter(prefix="/reconstructions", tags=["reconstructions"])


def _get_service(request: Request) -> ColmapService:
    return request.app.state.colmap_service


def _job_run_dir(service: ColmapService, job_id: str) -> Path:
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


@router.get("/{job_id}/pointcloud")
def get_reconstruction_pointcloud(job_id: str, request: Request) -> FileResponse:
    service = _get_service(request)
    record = service.store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        ply_path = service.export_pointcloud(record.paths)
    except Exception as exc:  # noqa: BLE001 - surface conversion failures to the client
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export point cloud: {exc}",
        ) from exc
    if ply_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No point cloud available; the reconstruction produced no sparse model.",
        )

    return FileResponse(ply_path, filename=f"reconstruction-{job_id}.ply", media_type="application/octet-stream")


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

