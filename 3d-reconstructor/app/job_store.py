from __future__ import annotations

from threading import Lock

from .domain import JobRecord, JobStatus, PipelinePaths, ReconstructionOptions, utc_now


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = Lock()

    def create_job(
        self,
        job_id: str,
        options: ReconstructionOptions,
        paths: PipelinePaths,
    ) -> dict[str, object]:
        now = utc_now()
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
            options=options,
            paths=paths,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record.to_dict()

    def list_jobs(self) -> list[dict[str, object]]:
        with self._lock:
            return [record.to_dict() for record in self._jobs.values()]

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_payload(self, job_id: str) -> dict[str, object] | None:
        record = self.get_job(job_id)
        return record.to_dict() if record else None

    def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record.status = status
            record.updated_at = utc_now()
            record.error = error

    def set_quality(self, job_id: str, quality: dict[str, object]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record.quality = quality
            record.updated_at = utc_now()

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record.logs.append(line)
            record.updated_at = utc_now()

    def add_command(self, job_id: str, command: list[str]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            record.commands.append(command)
            record.updated_at = utc_now()

