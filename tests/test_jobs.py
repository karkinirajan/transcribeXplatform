from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import jobs  # noqa: E402
from jobs import JobStatus, TooManyJobsError, create_job, finish_job, get_job, prune_jobs, remove_job  # noqa: E402


@pytest.fixture(autouse=True)
def empty_store():
    jobs._store.clear()
    yield
    jobs._store.clear()


def test_a_new_job_is_queued_and_findable():
    job = create_job("a.mp3")
    assert job.status is JobStatus.QUEUED
    assert get_job(job.id) is job


def test_finishing_a_job_records_the_time_and_removes_the_recording(tmp_path):
    temp = tmp_path / "t"
    temp.mkdir()
    (temp / "a.mp3").write_bytes(b"private audio")
    job = create_job("a.mp3", temp_dir=temp)
    before = time.time()
    finish_job(job, JobStatus.COMPLETED)
    assert job.status is JobStatus.COMPLETED
    assert job.finished_at is not None and job.finished_at >= before
    assert not temp.exists()


def test_a_failed_job_keeps_its_error(tmp_path):
    job = create_job("a.mp3", temp_dir=tmp_path)
    finish_job(job, JobStatus.FAILED, "boom")
    assert (job.status, job.error) == (JobStatus.FAILED, "boom")


def test_finished_jobs_expire_after_the_ttl_and_take_their_files_with_them(tmp_path):
    old_dir, fresh_dir, running_dir = (tmp_path / n for n in ("old", "fresh", "running"))
    for d in (old_dir, fresh_dir, running_dir):
        d.mkdir()
    old, fresh, running = create_job("o", old_dir), create_job("f", fresh_dir), create_job("r", running_dir)
    now = time.time()
    old.status, old.finished_at = JobStatus.COMPLETED, now - jobs.JOB_TTL_SECONDS - 1
    fresh.status, fresh.finished_at = JobStatus.FAILED, now - jobs.JOB_TTL_SECONDS + 60
    running.status = JobStatus.PROCESSING
    assert prune_jobs(now) == 1
    assert get_job(old.id) is None and not old_dir.exists()
    assert get_job(fresh.id) is fresh and fresh_dir.exists()
    assert get_job(running.id) is running  # a job still running is never expired, however old


def test_a_finished_job_exactly_at_the_ttl_is_kept():
    job = create_job("a")
    now = time.time()
    job.status, job.finished_at = JobStatus.COMPLETED, now - jobs.JOB_TTL_SECONDS
    assert prune_jobs(now) == 0


def test_the_store_is_capped_and_the_oldest_finished_jobs_make_room(monkeypatch):
    monkeypatch.setattr(jobs, "MAX_JOBS", 3)
    first, second, third = create_job("1"), create_job("2"), create_job("3")
    now = time.time()
    for offset, job in enumerate((first, second, third)):
        job.status, job.finished_at = JobStatus.COMPLETED, now - 100 + offset
    fourth = create_job("4")
    assert get_job(first.id) is None
    assert [get_job(j.id) for j in (second, third, fourth)] == [second, third, fourth]


def test_when_every_job_is_still_running_a_new_one_is_refused(monkeypatch):
    monkeypatch.setattr(jobs, "MAX_JOBS", 2)
    for name in ("1", "2"):
        create_job(name).status = JobStatus.PROCESSING
    with pytest.raises(TooManyJobsError):
        create_job("3")


def test_remove_job_forgets_it_and_its_files(tmp_path):
    temp = tmp_path / "t"
    temp.mkdir()
    job = create_job("a", temp_dir=temp)
    assert remove_job(job.id) is True
    assert get_job(job.id) is None and not temp.exists()
    assert remove_job(job.id) is False
    assert remove_job("not-a-job") is False


def test_a_snapshot_is_a_copy():
    job = create_job("a")
    job.add_message("one")
    snapshot = job.snapshot()
    job.add_message("two")
    assert snapshot["messages"] == ["one"]
    assert snapshot["filename"] == "a"
