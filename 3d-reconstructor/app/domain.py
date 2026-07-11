from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class ReconstructionOptions:
    project_id: str
    image_dir: str
    camera_model: str
    matcher: str
    dense: bool
    use_gpu: bool
    image_list_path: str | None = None
    max_image_size: int | None = None


@dataclass(slots=True)
class PipelinePaths:
    run_dir: str
    database_path: str
    sparse_dir: str
    dense_dir: str | None
    image_dir: str
    image_list_path: str | None = None


@dataclass(slots=True)
class UploadBatch:
    project_uuid: str
    image_dir: str
    absolute_dir: str
    file_count: int
    files: list[str]
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "project_uuid": self.project_uuid,
            "image_dir": self.image_dir,
            "absolute_dir": self.absolute_dir,
            "file_count": self.file_count,
            "files": self.files,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class JobRecord:
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    options: ReconstructionOptions
    paths: PipelinePaths
    commands: list[list[str]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    quality: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "options": asdict(self.options),
            "paths": asdict(self.paths),
            "commands": self.commands,
            "logs": self.logs,
            "error": self.error,
            "quality": self.quality,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
