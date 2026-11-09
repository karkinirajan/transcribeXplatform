"""
AI summarisation of finished transcripts.

Transcripts come out of the pipeline as `[HH:MM:SS] Speaker: text` markdown.
This module strips the timestamp scaffolding, sends the conversation to an LLM
and returns a short structured summary.

Long recordings exceed a single context window, so anything past
`MAX_SINGLE_PASS_CHARS` is summarised map-reduce style: each chunk is condensed
independently, then the condensations are merged into one final summary.

Uses the OPENAI_API_KEY that the OpenAI transcription backend already relies on
— no new credential for the user to set up.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Roughly 4 chars/token; ~30k chars keeps a single pass well inside the window
# while leaving room for the prompt and the response.
MAX_SINGLE_PASS_CHARS = 30_000
CHUNK_CHARS = 24_000

DEFAULT_MODEL = "gpt-4o-mini"

_TIMESTAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")
_HEADING_RE = re.compile(r"^#\s+")

SYSTEM_PROMPT = (
    "You summarise transcripts of conversations, meetings, interviews and talks. "
    "Be accurate and concise, and never invent details that are not in the transcript. "
    "Attribute points to the speaker labels used in the transcript when it matters."
)

SUMMARY_INSTRUCTIONS = """\
Summarise the transcript below in Markdown using exactly these sections, \
omitting any section that genuinely has no content:

## Overview
Two or three sentences on what this conversation was about.

## Key Points
- The substantive points, as bullets.

## Decisions
- Anything that was agreed or concluded.

## Action Items
- Concrete follow-ups, with the responsible speaker when stated.

Transcript:
"""

CHUNK_INSTRUCTIONS = """\
This is part {index} of {total} of a longer transcript. Condense it into dense \
bullet points capturing every substantive point, decision and action item. \
Do not add a preamble or a conclusion — this will be merged with the other parts.

Transcript part:
"""

MERGE_INSTRUCTIONS = """\
Below are ordered notes from consecutive parts of a single transcript. Merge them \
into one coherent summary using exactly these sections, omitting any that have no \
content: "## Overview", "## Key Points", "## Decisions", "## Action Items". \
Remove duplicates and keep chronological sense.

Notes:
"""


class SummaryNotConfiguredError(RuntimeError):
    """Raised when no API key is available for summarisation."""


class SummaryProviderError(RuntimeError):
    """Raised when the upstream AI provider rejects or fails the request."""


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    model: str
    chunks: int
    source_chars: int


def transcript_to_plain_text(markdown: str) -> str:
    """Drop the title heading and `[HH:MM:SS]` prefixes, keeping `Speaker: text`."""
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or _HEADING_RE.match(line):
            continue
        lines.append(_TIMESTAMP_RE.sub("", line))
    return "\n".join(lines)


def _chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on line boundaries so a speaker turn is never cut in half."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    for line in text.splitlines():
        # +1 for the newline we will re-join with.
        if length + len(line) + 1 > size and current:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks


def _get_client(api_key: str | None = None):
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise SummaryNotConfiguredError(
            "Summarisation needs an OpenAI API key. Set OPENAI_API_KEY in your .env file."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency is always bundled
        raise SummaryNotConfiguredError("The 'openai' package is not installed.") from exc

    return OpenAI(api_key=key)


def _complete(client, model: str, instructions: str, body: str) -> str:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": instructions + body},
            ],
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 — surface any SDK/API failure uniformly
        raise SummaryProviderError(f"Summarisation request failed: {exc}") from exc

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise SummaryProviderError("The model returned an empty summary.")
    return content


def summarize_transcript(
    markdown: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    title: str | None = None,
) -> SummaryResult:
    """
    Summarise a finished transcript.

    Args:
        markdown: transcript in `[HH:MM:SS] Speaker: text` form.
        model: chat model to use (default: gpt-4o-mini, or $SUMMARY_MODEL).
        api_key: override for OPENAI_API_KEY.
        title: optional recording title, given to the model as context.

    Raises:
        ValueError: the transcript is empty.
        SummaryNotConfiguredError: no API key available.
        SummaryProviderError: the provider call failed.
    """
    text = transcript_to_plain_text(markdown)
    if not text.strip():
        raise ValueError("Transcript is empty — nothing to summarise.")

    resolved_model = model or os.getenv("SUMMARY_MODEL") or DEFAULT_MODEL
    client = _get_client(api_key)
    header = f"Recording title: {title}\n\n" if title else ""

    if len(text) <= MAX_SINGLE_PASS_CHARS:
        summary = _complete(client, resolved_model, SUMMARY_INSTRUCTIONS, header + text)
        return SummaryResult(summary=summary, model=resolved_model, chunks=1, source_chars=len(text))

    # Map-reduce for long recordings.
    chunks = _chunk_text(text)
    notes: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        instructions = CHUNK_INSTRUCTIONS.format(index=index, total=len(chunks))
        notes.append(_complete(client, resolved_model, instructions, chunk))

    merged = "\n\n".join(f"### Part {i}\n{note}" for i, note in enumerate(notes, start=1))
    summary = _complete(client, resolved_model, MERGE_INSTRUCTIONS, header + merged)
    return SummaryResult(summary=summary, model=resolved_model, chunks=len(chunks), source_chars=len(text))


def summarization_available() -> bool:
    """True when a key is configured — used by /api/health to enable the UI button."""
    return bool(os.getenv("OPENAI_API_KEY"))
