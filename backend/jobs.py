from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    filename: str
    status: JobStatus = JobStatus.QUEUED
    messages: list[str] = field(default_factory=list)
    transcript: str | None = None
    error: str | None = None
    finished_at: float | None = None
    # Internal: paths to clean up after download
    _temp_dir: Path | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_message(self, text: str) -> None:
        with self._lock:
            self.messages.append(text)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "filename": self.filename,
                "status": self.status,
                "messages": list(self.messages),
                "transcript": self.transcript,
                "error": self.error,
            }


# Global in-memory store: fine for a single-process app.
#
# Finished jobs hold a whole transcript in memory and were never removed (only a DELETE call removed their files, and not the job
# itself), so a long-running server grew without bound. Finished jobs now expire after JOB_TTL_SECONDS, and at most MAX_JOBS are kept.
JOB_TTL_SECONDS = 3600
MAX_JOBS = 200

_store: dict[str, Job] = {}
_store_lock = threading.Lock()


class TooManyJobsError(RuntimeError):
    pass


def _finished(job: Job) -> bool:
    return job.status in (JobStatus.COMPLETED, JobStatus.FAILED)


def _forget(job: Job) -> None:
    if job._temp_dir:
        shutil.rmtree(job._temp_dir, ignore_errors=True)


def prune_jobs(now: float | None = None) -> int:
    """Drops finished jobs older than the TTL, and the oldest finished ones if there are still more than MAX_JOBS. Returns how many."""
    now = time.time() if now is None else now
    removed: list[Job] = []
    with _store_lock:
        for job_id, job in list(_store.items()):
            # finished_at is only ever set when a job finishes, so a job that is still running is never expired
            if job.finished_at is not None and now - job.finished_at > JOB_TTL_SECONDS:
                removed.append(_store.pop(job_id))
        over = len(_store) - MAX_JOBS + 1
        if over > 0:
            oldest_first = sorted((j for j in _store.values() if _finished(j)), key=lambda j: j.finished_at or 0)
            for job in oldest_first[:over]:
                removed.append(_store.pop(job.id))
    for job in removed:
        _forget(job)
    return len(removed)


def create_job(filename: str, temp_dir: Path | None = None) -> Job:
    prune_jobs()
    job = Job(id=str(uuid.uuid4()), filename=filename, _temp_dir=temp_dir)
    with _store_lock:
        if len(_store) >= MAX_JOBS:
            raise TooManyJobsError("Too many jobs are running. Try again when one has finished.")
        _store[job.id] = job
    return job


def finish_job(job: Job, status: JobStatus, error: str | None = None) -> None:
    """Marks a job finished (so it can expire) and removes its temporary files, which hold the uploaded recording."""
    job.error = error
    job.finished_at = time.time()
    job.status = status
    _forget(job)


def get_job(job_id: str) -> Job | None:
    with _store_lock:
        return _store.get(job_id)


def remove_job(job_id: str) -> bool:
    with _store_lock:
        job = _store.pop(job_id, None)
    if job is None:
        return False
    _forget(job)
    return True


def list_jobs() -> list[dict]:
    with _store_lock:
        return [j.snapshot() for j in _store.values()]
