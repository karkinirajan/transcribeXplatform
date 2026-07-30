from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import main as api  # noqa: E402
from summarize import SummaryNotConfiguredError, SummaryProviderError, SummaryResult  # noqa: E402

TRANSCRIPT = "[00:00:00] Mike: Let's ship on Friday.\n[00:00:10] Speaker 1: Agreed."


@pytest.fixture
def client():
    return TestClient(api.app)


def test_summarize_returns_summary(client, monkeypatch):
    captured = {}

    def fake(markdown, *, title=None, model=None):
        captured.update(markdown=markdown, title=title, model=model)
        return SummaryResult(summary="## Overview\nShipping Friday.", model="gpt-4o-mini",
                             chunks=1, source_chars=len(markdown))

    monkeypatch.setattr(api, "summarize_transcript", fake)

    response = client.post("/api/summarize", json={"transcript": TRANSCRIPT, "title": "Standup"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "## Overview\nShipping Friday."
    assert body["model"] == "gpt-4o-mini"
    assert body["chunks"] == 1
    assert captured["title"] == "Standup"


def test_summarize_passes_model_override(client, monkeypatch):
    captured = {}

    def fake(markdown, *, title=None, model=None):
        captured["model"] = model
        return SummaryResult(summary="s", model=model or "default", chunks=1, source_chars=1)

    monkeypatch.setattr(api, "summarize_transcript", fake)
    client.post("/api/summarize", json={"transcript": TRANSCRIPT, "model": "gpt-4o"})
    assert captured["model"] == "gpt-4o"


def test_summarize_missing_key_returns_503(client, monkeypatch):
    def fake(markdown, **kwargs):
        raise SummaryNotConfiguredError("Set OPENAI_API_KEY in your .env file.")

    monkeypatch.setattr(api, "summarize_transcript", fake)
    response = client.post("/api/summarize", json={"transcript": TRANSCRIPT})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_summarize_provider_failure_returns_502(client, monkeypatch):
    def fake(markdown, **kwargs):
        raise SummaryProviderError("upstream exploded")

    monkeypatch.setattr(api, "summarize_transcript", fake)
    response = client.post("/api/summarize", json={"transcript": TRANSCRIPT})

    assert response.status_code == 502
    assert "upstream exploded" in response.json()["detail"]


def test_summarize_empty_transcript_returns_400(client, monkeypatch):
    def fake(markdown, **kwargs):
        raise ValueError("Transcript is empty — nothing to summarise.")

    monkeypatch.setattr(api, "summarize_transcript", fake)
    response = client.post("/api/summarize", json={"transcript": "# title"})
    assert response.status_code == 400


def test_summarize_rejects_blank_body(client):
    # min_length=1 on the model means validation, not a provider round-trip.
    assert client.post("/api/summarize", json={"transcript": ""}).status_code == 422
    assert client.post("/api/summarize", json={}).status_code == 422


def test_health_reports_summarization_flag(client, monkeypatch):
    monkeypatch.setattr(api, "summarization_available", lambda: True)
    assert client.get("/api/health").json()["summarization"] is True

    monkeypatch.setattr(api, "summarization_available", lambda: False)
    assert client.get("/api/health").json()["summarization"] is False


def test_job_summary_404_for_unknown_job(client):
    assert client.post("/api/jobs/does-not-exist/summary").status_code == 404


def test_job_summary_409_when_not_completed(client, monkeypatch):
    from jobs import JobStatus, create_job

    job = create_job(filename="a.mp3", temp_dir=None)
    job.status = JobStatus.PROCESSING

    response = client.post(f"/api/jobs/{job.id}/summary")
    assert response.status_code == 409
    assert "processing" in response.json()["detail"]


def test_job_summary_uses_stored_transcript(client, monkeypatch):
    from jobs import JobStatus, create_job

    captured = {}

    def fake(markdown, *, title=None, model=None):
        captured.update(markdown=markdown, title=title)
        return SummaryResult(summary="done", model="m", chunks=1, source_chars=len(markdown))

    monkeypatch.setattr(api, "summarize_transcript", fake)

    job = create_job(filename="meeting.mp3", temp_dir=None)
    job.status = JobStatus.COMPLETED
    job.transcript = TRANSCRIPT

    response = client.post(f"/api/jobs/{job.id}/summary")

    assert response.status_code == 200
    assert response.json()["summary"] == "done"
    assert captured["markdown"] == TRANSCRIPT
    assert captured["title"] == "meeting"
