from __future__ import annotations

import pytest
from summarize import (
    CHUNK_CHARS,
    MAX_SINGLE_PASS_CHARS,
    SummaryNotConfiguredError,
    SummaryProviderError,
    _chunk_text,
    summarization_available,
    summarize_transcript,
    transcript_to_plain_text,
)

SAMPLE = """# Weekly sync

[00:00:00] Mike: Morning everyone, let's start with the roadmap.
[00:00:12] Speaker 1: I finished the ingest pipeline yesterday.
[00:01:30] Mike: Great — can you write it up by Friday?
"""


# ---------------------------------------------------------------------------
# Fakes — no network in the test suite
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, replies, calls):
        self._replies = replies
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        reply = self._replies[min(len(self._calls) - 1, len(self._replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return _FakeResponse(reply)


class FakeClient:
    def __init__(self, *replies):
        self.calls: list[dict] = []
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions(list(replies), self.calls)


@pytest.fixture
def fake_openai(monkeypatch):
    """Patch _get_client so no real OpenAI client is ever constructed."""
    holder = {}

    def install(*replies):
        client = FakeClient(*replies)
        holder["client"] = client
        monkeypatch.setattr("summarize._get_client", lambda api_key=None: client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return install


# ---------------------------------------------------------------------------
# transcript_to_plain_text
# ---------------------------------------------------------------------------

def test_plain_text_strips_timestamps_and_heading():
    text = transcript_to_plain_text(SAMPLE)
    assert "[00:00:00]" not in text
    assert "# Weekly sync" not in text
    assert text.startswith("Mike: Morning everyone")
    assert "Speaker 1: I finished the ingest pipeline yesterday." in text


def test_plain_text_drops_blank_lines():
    assert transcript_to_plain_text("\n\n[00:00:01] A: hi\n\n\n") == "A: hi"


def test_plain_text_keeps_lines_without_timestamps():
    assert transcript_to_plain_text("A plain note") == "A plain note"


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------

def test_chunk_text_respects_size_limit():
    text = "\n".join(f"Speaker {i}: {'word ' * 20}" for i in range(2000))
    chunks = _chunk_text(text, size=5000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 5000 for chunk in chunks)


def test_chunk_text_never_splits_a_line():
    text = "\n".join(f"line-{i}" for i in range(100))
    rejoined = "\n".join(_chunk_text(text, size=50))
    assert rejoined == text


def test_chunk_text_single_chunk_when_small():
    assert _chunk_text("short", size=CHUNK_CHARS) == ["short"]


# ---------------------------------------------------------------------------
# summarize_transcript — single pass
# ---------------------------------------------------------------------------

def test_summarize_single_pass(fake_openai):
    client = fake_openai("## Overview\nA roadmap sync.")
    result = summarize_transcript(SAMPLE, title="Weekly sync")

    assert result.summary == "## Overview\nA roadmap sync."
    assert result.chunks == 1
    assert result.model == "gpt-4o-mini"
    assert len(client.calls) == 1

    prompt = client.calls[0]["messages"][1]["content"]
    assert "Recording title: Weekly sync" in prompt
    assert "Mike: Morning everyone" in prompt
    assert "[00:00:00]" not in prompt


def test_summarize_respects_model_override(fake_openai):
    client = fake_openai("summary")
    result = summarize_transcript(SAMPLE, model="gpt-4o")
    assert result.model == "gpt-4o"
    assert client.calls[0]["model"] == "gpt-4o"


def test_summarize_uses_summary_model_env(fake_openai, monkeypatch):
    monkeypatch.setenv("SUMMARY_MODEL", "gpt-4.1-mini")
    fake_openai("summary")
    assert summarize_transcript(SAMPLE).model == "gpt-4.1-mini"


def test_summarize_reports_source_size(fake_openai):
    fake_openai("summary")
    result = summarize_transcript(SAMPLE)
    assert result.source_chars == len(transcript_to_plain_text(SAMPLE))


# ---------------------------------------------------------------------------
# summarize_transcript — map-reduce
# ---------------------------------------------------------------------------

def test_summarize_long_transcript_uses_map_reduce(fake_openai):
    long_text = "\n".join(f"[00:00:0{i % 10}] Speaker 1: {'word ' * 40}" for i in range(3000))
    assert len(transcript_to_plain_text(long_text)) > MAX_SINGLE_PASS_CHARS

    client = fake_openai("chunk notes", "chunk notes", "chunk notes", "merged summary")
    result = summarize_transcript(long_text)

    assert result.chunks > 1
    # one call per chunk plus the merge call
    assert len(client.calls) == result.chunks + 1
    assert result.summary == "merged summary"

    merge_prompt = client.calls[-1]["messages"][1]["content"]
    assert "### Part 1" in merge_prompt
    assert "Merge them" in merge_prompt


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------

def test_summarize_empty_transcript_raises():
    with pytest.raises(ValueError, match="empty"):
        summarize_transcript("# Only a title\n\n")


def test_summarize_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SummaryNotConfiguredError, match="OPENAI_API_KEY"):
        summarize_transcript(SAMPLE)


def test_summarize_wraps_provider_errors(fake_openai):
    fake_openai(RuntimeError("429 rate limited"))
    with pytest.raises(SummaryProviderError, match="rate limited"):
        summarize_transcript(SAMPLE)


def test_summarize_rejects_empty_model_output(fake_openai):
    fake_openai("   ")
    with pytest.raises(SummaryProviderError, match="empty summary"):
        summarize_transcript(SAMPLE)


# ---------------------------------------------------------------------------
# availability probe
# ---------------------------------------------------------------------------

def test_summarization_available_follows_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert summarization_available() is True
    monkeypatch.delenv("OPENAI_API_KEY")
    assert summarization_available() is False
