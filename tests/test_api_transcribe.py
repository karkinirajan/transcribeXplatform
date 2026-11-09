from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import jobs  # noqa: E402
import main as api  # noqa: E402

TEMP = Path(tempfile.gettempdir())


def leftovers() -> set[Path]:
    return set(TEMP.glob("transcribe_*"))


@pytest.fixture
def client():
    jobs._store.clear()
    yield TestClient(api.app)
    jobs._store.clear()


@pytest.fixture
def started(monkeypatch):
    """Replaces the worker so no transcription runs; records what the endpoint handed it."""
    calls = []

    def fake_run_job(job, input_path, output_path, backend, model, language_code, title):
        calls.append({"job": job, "input": input_path, "output": output_path, "backend": backend, "model": model, "language": language_code, "title": title})

    monkeypatch.setattr(api, "_run_job", fake_run_job)
    return calls


def upload(client, name="talk.mp3", content=b"audio", **fields):
    data = {"backend": "assemblyai", **fields}
    return client.post("/api/transcribe", files={"file": (name, content, "audio/mpeg")}, data=data)


def test_a_plain_upload_starts_a_job(client, started):
    response = upload(client, title="Weekly sync", language="en", model="base")
    assert response.status_code == 202
    assert jobs.get_job(response.json()["job_id"]) is not None
    call = started[0]
    assert call["input"].read_bytes() == b"audio"
    assert (call["backend"], call["model"], call["language"], call["title"]) == ("assemblyai", "base", "en", "Weekly sync")


@pytest.mark.parametrize("hostile", ["../../escape.mp3", "..\\..\\escape.mp3", "/tmp/escape.mp3", "a/../../escape.mp3"])
def test_a_hostile_file_name_cannot_write_outside_the_temp_directory(client, started, hostile):
    response = upload(client, name=hostile)
    assert response.status_code == 202
    call = started[0]
    assert call["input"].name == "escape.mp3"
    assert call["input"].parent == call["output"].parent
    assert call["input"].parent.name.startswith("transcribe_")
    assert call["input"].parent.parent == TEMP


def test_the_title_is_tidied_before_it_reaches_the_worker(client, started):
    upload(client, title="  Weekly   sync\x00 notes  ")
    assert started[0]["title"] == "Weekly sync notes"
    upload(client, title="   ")
    assert started[1]["title"] is None


def test_the_job_is_named_after_the_safe_name_not_the_one_sent(client, started):
    job_id = upload(client, name="../../etc/talk.mp3").json()["job_id"]
    assert jobs.get_job(job_id).filename == "talk.mp3"


@pytest.mark.parametrize("name", ["talk.exe", "talk.mp3.sh", "talk", "talk.html", ".mp3x"])
def test_only_audio_and_video_extensions_are_accepted(client, started, name):
    assert upload(client, name=name).status_code == 400
    assert started == []


def test_an_unknown_backend_is_refused(client, started):
    assert upload(client, backend="evil").status_code == 400
    assert started == []


@pytest.mark.parametrize(("field", "value"), [("language", "english"), ("language", "en;rm -rf"), ("model", "-rf"), ("model", "a b"), ("model", "x" * 101)])
def test_bad_language_and_model_values_are_refused_before_anything_is_stored(client, started, field, value):
    before = leftovers()
    assert upload(client, **{field: value}).status_code == 400
    assert started == []
    assert leftovers() == before


def test_a_file_over_the_limit_is_refused_with_413_and_leaves_nothing_behind(client, started, monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_MAX_UPLOAD_MB", "1")
    before = leftovers()
    response = upload(client, content=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]
    assert started == []
    assert jobs._store == {}
    assert leftovers() == before


def test_a_file_exactly_at_the_limit_is_accepted(client, started, monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_MAX_UPLOAD_MB", "1")
    assert upload(client, content=b"x" * (1024 * 1024)).status_code == 202


def test_a_declared_length_far_over_the_limit_is_refused_without_reading(client, started, monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_MAX_UPLOAD_MB", "1")
    response = client.post(
        "/api/transcribe",
        files={"file": ("talk.mp3", b"x", "audio/mpeg")},
        data={"backend": "assemblyai"},
        headers={"content-length": str(50 * 1024 * 1024)},
    )
    assert response.status_code in (413, 400)


def test_when_too_many_jobs_are_running_the_upload_is_refused_and_cleaned_up(client, started, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_JOBS", 1)
    jobs.create_job("busy").status = jobs.JobStatus.PROCESSING
    before = leftovers()
    assert upload(client).status_code == 503
    assert leftovers() == before


def test_delete_removes_the_job_and_a_second_delete_is_404(client, started):
    job_id = upload(client).json()["job_id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404


def test_cors_allows_only_the_apps_own_origins_and_methods(client):
    ok = client.options("/api/transcribe", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "PUT" not in ok.headers.get("access-control-allow-methods", "")
    bad = client.options("/api/transcribe", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_the_server_is_started_on_loopback_by_default():
    source = (Path(__file__).parent.parent / "backend" / "main.py").read_text(encoding="utf-8")
    assert '"0.0.0.0"' not in source
    assert 'os.getenv("TRANSCRIBE_HOST", "127.0.0.1")' in source


class TestRunJob:
    """The worker itself, with the media tools replaced."""

    def _patch(self, monkeypatch, tmp_path, *, transcript="# Title\n\nHello", fail=None):
        import ffmpeg_audio
        import format_md
        import media_probe

        class Info:
            has_audio = True
            duration_seconds = 60

        monkeypatch.setattr(media_probe, "probe_media", lambda p: Info())
        wav = tmp_path / "wav" / "x.wav"

        def normalize(path, wav_dir):
            wav_dir.mkdir(parents=True, exist_ok=True)
            wav.write_bytes(b"w")
            return type("R", (), {"output_wav_path": wav})()

        monkeypatch.setattr(ffmpeg_audio, "normalize_to_wav", normalize)

        def save(turns, out, title=None):
            out.write_text(transcript, encoding="utf-8")
            return out

        monkeypatch.setattr(format_md, "save_transcript_markdown", save)

        def transcribe(job, backend, model, wav_path, language):
            if fail:
                raise RuntimeError(fail)
            return []

        monkeypatch.setattr(api, "_transcribe", transcribe)

    def _job(self, tmp_path):
        (tmp_path / "in.mp3").write_bytes(b"recording")
        return jobs.create_job("in.mp3", temp_dir=tmp_path), tmp_path / "in.mp3", tmp_path / "in.md"

    def test_success_keeps_the_transcript_in_memory_and_deletes_the_recording(self, client, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        job, inp, out = self._job(tmp_path)
        api._run_job(job, inp, out, "openai", "", None, "T")
        assert job.status is jobs.JobStatus.COMPLETED and job.transcript == "# Title\n\nHello" and job.error is None
        assert job.messages[-1] == "Done!"
        assert not tmp_path.exists()
        assert job.finished_at is not None

    def test_failure_records_the_error_and_still_deletes_the_recording(self, client, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path, fail="provider said no")
        job, inp, out = self._job(tmp_path)
        api._run_job(job, inp, out, "openai", "", None, None)
        assert job.status is jobs.JobStatus.FAILED and job.error == "provider said no"
        assert job.messages[-1] == "Error: provider said no"
        assert not tmp_path.exists()


class TestCrossSiteProtection:
    """The API is on the user's own machine; web pages must not be able to use it."""

    def test_a_cross_site_upload_is_refused_before_anything_is_stored(self, client, started):
        before = leftovers()
        response = client.post(
            "/api/transcribe",
            files={"file": ("talk.mp3", b"x", "audio/mpeg")},
            data={"backend": "assemblyai"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403
        assert started == [] and jobs._store == {} and leftovers() == before

    @pytest.mark.parametrize("origin", ["null", "http://localhost:3000.evil.example", "http://127.0.0.1:3002", "https://127.0.0.1:3000", "file://"])
    def test_look_alike_and_opaque_origins_are_refused(self, client, started, origin):
        response = client.post("/api/transcribe", files={"file": ("a.mp3", b"x", "audio/mpeg")}, data={"backend": "assemblyai"}, headers={"Origin": origin})
        assert response.status_code == 403

    @pytest.mark.parametrize("method", ["POST", "DELETE"])
    def test_every_state_changing_method_is_checked(self, client, method):
        assert client.request(method, "/api/jobs/anything", headers={"Origin": "https://evil.example"}).status_code == 403

    @pytest.mark.parametrize("origin", api.ALLOWED_ORIGINS)
    def test_the_apps_own_origins_are_accepted(self, client, started, origin):
        response = client.post("/api/transcribe", files={"file": ("a.mp3", b"x", "audio/mpeg")}, data={"backend": "assemblyai"}, headers={"Origin": origin})
        assert response.status_code == 202

    def test_a_request_with_no_origin_is_accepted(self, client, started):
        assert upload(client).status_code == 202

    def test_reads_are_not_blocked_by_the_origin_rule(self, client):
        assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200

    @pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "127.0.0.1.evil.example", "attacker.test:8000"])
    def test_a_host_that_is_not_this_machine_is_refused_so_dns_rebinding_cannot_reach_the_api(self, client, host):
        assert client.get("/api/health", headers={"Host": host}).status_code == 400

    @pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000", "testserver"])
    def test_this_machine_is_accepted(self, client, host):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200
