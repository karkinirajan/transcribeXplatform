from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — resolve utilities before any local imports
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "utilities_data" / "transcribe"))

from dotenv import load_dotenv

# In a packaged install the app directory is read-only, so API keys live in the
# per-user config directory that Electron passes down (app.getPath("userData")).
# The repo-root .env still wins for `make dev`, where it is the obvious place to
# look. First value loaded wins — python-dotenv does not override by default.
_CONFIG_DIR = os.getenv("TRANSCRIBE_CONFIG_DIR")
if _CONFIG_DIR:
    load_dotenv(Path(_CONFIG_DIR) / ".env")
load_dotenv(_ROOT / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from jobs import Job, JobStatus, TooManyJobsError, create_job, finish_job, get_job, remove_job
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from summarize import (
    SummaryNotConfiguredError,
    SummaryProviderError,
    summarization_available,
    summarize_transcript,
)
from uploads import (
    UploadTooLargeError,
    clean_language,
    clean_model,
    clean_title,
    copy_limited,
    max_upload_bytes,
    safe_upload_name,
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Transcribe API", version="1.0.0")

ALLOWED_ORIGINS = [
    "http://localhost:3000",   # Next.js dev
    "http://127.0.0.1:3000",  # Next.js dev (127.0.0.1), and the packaged desktop app
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "app://.",                 # Electron production
]

# The API listens on the user's own machine, but a web page they visit can still send requests to it, and a page on an attacker's
# domain can be made to resolve to 127.0.0.1 ("DNS rebinding"). Two checks close both:
#  - the Host header must name this machine (a rebound page's Host is the attacker's domain);
#  - a state-changing request that carries an Origin header must come from one of this app's own origins (a browser always sends Origin
#    on a cross-site POST). Without them, any site could upload a file to the user's transcription account.
# "testserver" is the host name Starlette's test client uses.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


@app.middleware("http")
async def refuse_cross_site_writes(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

_executor = ThreadPoolExecutor(max_workers=4)

VALID_BACKENDS = {"assemblyai", "openai", "deepgram", "whisper"}

# ---------------------------------------------------------------------------
# Health / capability check
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """Report which backends are available based on installed packages and env vars."""
    assemblyai_ready = bool(os.getenv("ASSEMBLYAI_API_KEY"))
    openai_ready = bool(os.getenv("OPENAI_API_KEY"))
    deepgram_ready = bool(os.getenv("DEEPGRAM_API_KEY"))

    whisper_ready = False
    try:
        import faster_whisper  # noqa: F401
        whisper_ready = True
    except ImportError:
        pass

    return {
        "status": "ok",
        "backends": {
            "assemblyai": assemblyai_ready,
            "openai": openai_ready,
            "deepgram": deepgram_ready,
            "whisper": whisper_ready,
        },
        "summarization": summarization_available(),
    }


# ---------------------------------------------------------------------------
# Transcription job runner (runs in thread pool)
# ---------------------------------------------------------------------------

def _run_job(
    job: Job,
    input_path: Path,
    output_path: Path,
    backend: str,
    model: str,
    language_code: str | None,
    title: str | None,
) -> None:
    from ffmpeg_audio import normalize_to_wav
    from format_md import save_transcript_markdown
    from media_probe import probe_media

    try:
        job.status = JobStatus.PROCESSING
        job.add_message(f"Processing: {input_path.name}")

        # --- Probe ---
        media_info = probe_media(input_path)
        if not media_info.has_audio:
            raise ValueError("File has no audio stream.")

        if media_info.duration_seconds:
            job.add_message(f"Duration: {media_info.duration_seconds / 60:.1f} minutes")

        # --- Normalize to 16 kHz mono WAV ---
        job.add_message("Normalizing audio to 16 kHz mono WAV…")
        wav_dir = output_path.parent / "wav"
        wav_dir.mkdir(parents=True, exist_ok=True)
        audio_result = normalize_to_wav(input_path, wav_dir)
        wav_path = audio_result.output_wav_path
        job.add_message("Audio normalized.")

        # --- Transcribe ---
        turns = _transcribe(job, backend, model, wav_path, language_code)

        speaker_count = len({t.speaker_label for t in turns})
        job.add_message(f"Detected {speaker_count} speaker(s), {len(turns)} segment(s).")

        # --- Save markdown ---
        md_path = save_transcript_markdown(
            turns,
            output_path,
            title=title or input_path.stem,
        )
        job.transcript = md_path.read_text(encoding="utf-8")
        job.add_message("Done!")
        finish_job(job, JobStatus.COMPLETED)

    except Exception as exc:
        job.add_message(f"Error: {exc}")
        finish_job(job, JobStatus.FAILED, str(exc))


def _transcribe(job: Job, backend: str, model: str, wav_path: Path, language_code: str | None):
    """Dispatch to the correct provider and return a list of SpeakerTurn objects."""

    if backend == "assemblyai":
        from format_md import assemblyai_to_speaker_turns
        from transcribe_aai import _extract_speaker_names, transcribe_audio_file

        job.add_message("Uploading to AssemblyAI…")
        transcript = transcribe_audio_file(wav_path, language_code=language_code or None)
        job.add_message(f"AssemblyAI complete. Words: {len(transcript.words or [])}")
        speaker_names = _extract_speaker_names(transcript)
        return assemblyai_to_speaker_turns(transcript.utterances, speaker_names=speaker_names)

    if backend == "openai":
        from transcribe_openai import transcribe_with_openai

        _model = model or "gpt-4o-mini-transcribe"
        job.add_message(f"Uploading to OpenAI ({_model})…")
        turns = transcribe_with_openai(wav_path, model=_model, language_code=language_code or None)
        job.add_message(f"OpenAI complete. Segments: {len(turns)}")
        return turns

    if backend == "deepgram":
        from transcribe_deepgram import transcribe_with_deepgram

        _model = model or "nova-3"
        job.add_message(f"Uploading to Deepgram ({_model})…")
        turns = transcribe_with_deepgram(wav_path, model=_model, language_code=language_code or None)
        job.add_message(f"Deepgram complete. Segments: {len(turns)}")
        return turns

    if backend == "whisper":
        from transcribe_whisper import transcribe_with_whisper

        _model = model or "base"
        job.add_message(f"Transcribing locally with Whisper ({_model})…")
        turns = transcribe_with_whisper(wav_path, model_size=_model, language_code=language_code or None)
        job.add_message(f"Whisper complete. Segments: {len(turns)}")
        return turns

    raise ValueError(f"Unknown backend: {backend!r}")


# ---------------------------------------------------------------------------
# POST /api/transcribe — upload file and start job
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".ogg", ".aac", ".m4a", ".wma",
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".wmv",
}


@app.post("/api/transcribe", status_code=202)
async def start_transcription(
    request: Request,
    file: UploadFile = File(...),
    backend: str = Form("assemblyai"),
    model: str = Form(""),
    language: str = Form(""),
    title: str = Form(""),
):
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Provide an audio or video file.",
        )

    if backend not in VALID_BACKENDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown backend '{backend}'. Choose from: {', '.join(sorted(VALID_BACKENDS))}",
        )

    try:
        language_code = clean_language(language)
        model_name = clean_model(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clean_name = clean_title(title)

    limit = max_upload_bytes()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"The file is larger than the {limit // (1024 * 1024)} MB limit.")

    # The stored name is made from the browser's file name, so it is sanitised: only a plain name ever lands in the temp directory.
    stored_name = safe_upload_name(file.filename, suffix)
    temp_dir = Path(tempfile.mkdtemp(prefix="transcribe_"))
    input_path = temp_dir / stored_name
    output_path = temp_dir / (Path(stored_name).stem + ".md")

    def _save() -> None:
        with open(input_path, "wb") as f:
            copy_limited(file.file, f, limit)

    try:
        # a blocking copy of a large file must not stall the event loop that serves every other request
        await run_in_threadpool(_save)
    except UploadTooLargeError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except OSError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Failed to save the upload.") from exc

    try:
        job = create_job(filename=stored_name, temp_dir=temp_dir)
    except TooManyJobsError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _run_job,
        job,
        input_path,
        output_path,
        backend,
        model_name,
        language_code,
        clean_name,
    )

    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id} — poll status
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.snapshot()


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/events — SSE live progress stream
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def _stream():
        sent = 0
        while True:
            snapshot = job.snapshot()
            new_msgs = snapshot["messages"][sent:]
            for msg in new_msgs:
                yield f"data: {json.dumps({'type': 'message', 'text': msg})}\n\n"
            sent += len(new_msgs)

            if snapshot["status"] in (JobStatus.COMPLETED, JobStatus.FAILED):
                yield f"data: {json.dumps({'type': 'done', 'status': snapshot['status'], 'error': snapshot['error']})}\n\n"
                return

            await asyncio.sleep(0.3)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/transcript — get transcript content
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/transcript")
def download_transcript(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not completed yet")
    if not job.transcript:
        raise HTTPException(status_code=404, detail="Transcript not available")

    return JSONResponse(content={
        "transcript": job.transcript,
        "filename": f"{Path(job.filename).stem}.md",
    })


# ---------------------------------------------------------------------------
# POST /api/summarize — AI summary of a finished transcript
# ---------------------------------------------------------------------------

class SummarizeRequest(BaseModel):
    transcript: str = Field(..., min_length=1, description="Transcript markdown to summarise")
    title: str | None = Field(None, description="Recording title, used as context")
    model: str | None = Field(None, description="Override the summarisation model")


@app.post("/api/summarize")
def summarize(payload: SummarizeRequest):
    try:
        result = summarize_transcript(
            payload.transcript,
            title=payload.title,
            model=payload.model or None,
        )
    except SummaryNotConfiguredError as exc:
        # 503: the server is fine, it just has no key configured.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SummaryProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "summary": result.summary,
        "model": result.model,
        "chunks": result.chunks,
        "source_chars": result.source_chars,
    }


@app.post("/api/jobs/{job_id}/summary")
def summarize_job(job_id: str, model: str = Form("")):
    """Summarise a completed job's transcript without re-uploading it."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED or not job.transcript:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not completed yet")

    return summarize(SummarizeRequest(
        transcript=job.transcript,
        title=Path(job.filename).stem,
        model=model or None,
    ))


# ---------------------------------------------------------------------------
# DELETE /api/jobs/{job_id} — clean up temp files
# ---------------------------------------------------------------------------

@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return None


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    # Loopback by default: this API spends the owner's transcription API keys and has no sign-in, so it must not be reachable from the
    # network. (It used to bind every interface.) Set TRANSCRIBE_HOST only if you put something with authentication in front of it.
    uvicorn.run("main:app", host=os.getenv("TRANSCRIBE_HOST", "127.0.0.1"), port=8000, reload=True)
