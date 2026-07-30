# Transcribe

Audio and video transcription with speaker identification — available as a **CLI tool**, **web app**, and **cross-platform desktop app**.

---

## Providers

| Provider | Tier | Price | Speaker ID | Languages |
|---|---|---|---|---|
| [AssemblyAI](https://assemblyai.com) | Freemium | $0.17 / hr · **$50 free credits** | ✅ With names | 99+ |
| [Deepgram Nova-3](https://deepgram.com) | Freemium | $0.26 / hr · **12 000 min / yr free** | ✅ Labels | 40+ |
| [OpenAI Whisper](https://platform.openai.com) | Paid | $0.18 – $0.36 / hr | ✗ | 99+ |
| Whisper (local) | **Free** | Free forever | ✗ | 99+ |

> **No upfront payment required** for AssemblyAI, Deepgram, or the local Whisper option.
> OpenAI requires a funded account but has no minimum spend.

---

## Features

- **Four transcription backends** — pick the right trade-off between cost, accuracy, and privacy
- **Speaker diarization** — AssemblyAI and Deepgram identify multiple speakers; AssemblyAI also detects speaker names from conversation context
- **Universal format pipeline** — any audio or video file is normalised to 16 kHz mono WAV before upload via ffmpeg
- **Real-time progress** — Server-Sent Events stream log lines to the UI as they happen
- **Markdown output** — timestamped `[HH:MM:SS] Speaker: text` format
- **One-click AI summary** — a **Summarize** button on every finished transcript produces an overview, key points, decisions and action items; long recordings are summarised map-reduce style
- **Three usage modes** — CLI, web browser, and Electron desktop app
- **Self-contained installers** — Python, ffmpeg and Node are bundled; users install nothing else
- **148 automated tests** — pytest suite covers all providers, the summarizer, the API and edge cases

---

## Quick Start

> **Just want the app?** Grab an installer from
> [Releases](https://github.com/karkinirajan/transcribe/releases) — they bundle
> Python, ffmpeg and Node, so there is nothing else to install.

```bash
# 1. Clone
git clone https://github.com/karkinirajan/transcribe
cd transcribe

# 2. Configure
cp .env.example .env
# Edit .env — add at least one API key (or use --backend whisper for free local mode)

# 3. Install — uv creates the venv and installs everything from uv.lock
make install

# 4-A. Run as web app (two terminals)
make dev-api      # FastAPI backend on :8000
make dev-web      # Next.js frontend on :3000

# 4-B. Run as desktop app
make dev          # Electron — starts both servers and opens the window
```

Python tooling is managed with [uv](https://docs.astral.sh/uv/). If you do not
have it: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

---

## Installation

### System dependencies

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows
winget install FFmpeg
```

> Not needed if you installed from a release artifact — ffmpeg and ffprobe are
> bundled inside the app.

### Python dependencies

```bash
uv sync                      # core: AssemblyAI, Deepgram, OpenAI
uv sync --extra whisper      # adds faster-whisper for offline transcription
```

`uv sync` installs the exact versions in `uv.lock`, which is resolved for
Linux, macOS and Windows on x64 and arm64.

### Frontend & Electron

```bash
cd frontend && npm install
cd electron && npm install
```

Or all at once with `make install`.

---

## Configuration

Copy `.env.example` to `.env` and fill in the keys for the providers you want:

```env
ASSEMBLYAI_API_KEY=   # https://assemblyai.com  — free $50 credits on sign-up
DEEPGRAM_API_KEY=     # https://deepgram.com    — 12 000 min/yr free tier
OPENAI_API_KEY=       # https://platform.openai.com — pay-per-use, no free tier
# Whisper (local) requires no key — install faster-whisper instead
```

The backend reports which providers are currently available at `GET /api/health`.

---

## Usage

### CLI

```bash
# Basic — saves transcript.md in the current directory
transcribe audio.mp3

# Choose backend
transcribe interview.mp4 --backend deepgram
transcribe meeting.mp4   --backend whisper --model small

# Full options
transcribe audio.mp3 \
  --backend assemblyai \
  --language es \
  --title "Team standup 2026-04-21" \
  --output ~/Documents/standup.md \
  --keep-wav
```

**Backends**

| Flag | Description |
|------|-------------|
| `assemblyai` | Cloud, speaker diarization + name detection, 99+ languages |
| `deepgram` | Cloud, fast, speaker labels, 40+ languages |
| `openai` | Cloud, GPT-4o powered, no diarization |
| `whisper` | Local, free, offline, no diarization |

**CLI options**

```
positional:
  input_file              Path to audio or video file

optional:
  -o, --output PATH       Output .md path (default: <filename>.md in cwd)
  -b, --backend NAME      assemblyai | openai | deepgram | whisper
  -m, --model NAME        Provider-specific model (see table below)
  -l, --language CODE     BCP-47 code e.g. en, es, fr. Default: auto-detect
  -t, --title TEXT        Markdown document title
      --keep-wav          Retain the normalised WAV file
```

**Model options per backend**

| Backend | Models |
|---------|--------|
| `assemblyai` | Universal (fixed — no selection) |
| `deepgram` | `nova-3` (default), `nova-2`, `enhanced`, `base` |
| `openai` | `gpt-4o-mini-transcribe` (default), `gpt-4o-transcribe`, `whisper-1` |
| `whisper` | `tiny`, `base` (default), `small`, `medium`, `large-v3-turbo` |

### Web app

```bash
make dev-api   # terminal 1
make dev-web   # terminal 2
```

Open `http://localhost:3000`, choose a provider, drag-and-drop your file.

### Desktop app (Electron)

```bash
make dev
```

Starts both servers and opens the Electron window automatically.

---

## Output format

```markdown
# Interview with Jordan

[00:00:13] Jordan: Hey, can you hear me okay?
[00:00:15] Lauren: Loud and clear. How are you?
[00:00:18] Jordan: Good, thanks. Let's get started.
[00:01:26] Speaker 1: So the main agenda today is...
```

- AssemblyAI detects real speaker names from conversation context
- Falls back to `Speaker 1`, `Speaker 2`, … when names cannot be detected
- Providers without diarization output all speech under `Speaker 1`

---

## Architecture

```
transcribe/
├── utilities_data/transcribe/   # Core transcription library (Python)
│   ├── media_probe.py           # ffprobe — detect streams, duration
│   ├── ffmpeg_audio.py          # Normalize any file → 16 kHz mono WAV
│   ├── format_md.py             # SpeakerTurn → Markdown renderer
│   ├── transcribe_aai.py        # AssemblyAI provider
│   ├── transcribe_openai.py     # OpenAI Whisper API provider
│   ├── transcribe_deepgram.py   # Deepgram REST API provider
│   ├── transcribe_whisper.py    # faster-whisper local provider
│   └── summarize.py             # AI summary, map-reduce for long transcripts
│
├── backend/                     # FastAPI REST API
│   ├── main.py                  # Endpoints, job runner, SSE stream
│   └── jobs.py                  # Thread-safe in-memory job store
│
├── frontend/                    # Next.js 16 + Tailwind CSS
│   └── app/components/
│       ├── TranscribeApp.tsx    # Root — state machine, provider cards
│       ├── DropZone.tsx         # Drag-and-drop file picker
│       ├── ProgressView.tsx     # Live SSE progress log
│       └── TranscriptView.tsx   # Summarize button, copy, .md / .txt download
│
├── electron/                    # Electron cross-platform wrapper
│   ├── main.js                  # Spawns bundled Python + Next.js, opens window
│   ├── preload.js               # Minimal context bridge
│   ├── electron-builder.yml     # Installer targets for Linux / Windows / macOS
│   └── build-resources/         # App icon and macOS entitlements
│
├── scripts/                     # Packaging pipeline
│   ├── bundle_runtime.py        # uv → relocatable CPython + wheels
│   ├── fetch_ffmpeg.py          # Static ffmpeg/ffprobe per platform
│   ├── build_frontend.mjs       # Next.js standalone bundle
│   └── build_installers.py      # Orchestrates everything → installers
│
├── packaging/arch/PKGBUILD      # Native Arch/CachyOS package (makepkg)
│
├── executable_scripts/transcribe  # CLI entry point
├── pyproject.toml + uv.lock       # uv-managed dependencies (all platforms)
└── tests/                         # 148 pytest tests
```

### Request flow

```
Browser / Electron window
    │  POST /api/transcribe  (multipart form)
    ▼
Next.js rewrite proxy  →  FastAPI :8000
    │
    ├── ThreadPoolExecutor
    │       ├── probe_media()      — ffprobe
    │       ├── normalize_to_wav() — ffmpeg → 16 kHz WAV
    │       └── transcribe_*()     — provider API or local model
    │                   │
    │           SpeakerTurn list
    │                   │
    │           format_md.py  →  transcript.md
    │
    │  GET /api/jobs/{id}/events   (SSE — real-time progress)
    ◄── data: {"type":"message","text":"..."}
    │
    │  GET /api/jobs/{id}/transcript
    ◄── {"transcript": "# Title\n[00:00:00] ...", "filename": "..."}
```

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Available backends and their readiness |
| `POST` | `/api/transcribe` | Upload file, start job → `{job_id}` |
| `GET` | `/api/jobs/{id}` | Poll status, messages, transcript |
| `GET` | `/api/jobs/{id}/events` | SSE real-time progress stream |
| `GET` | `/api/jobs/{id}/transcript` | Fetch completed transcript |
| `POST` | `/api/summarize` | AI summary of a transcript → `{summary, model, chunks}` |
| `POST` | `/api/jobs/{id}/summary` | Summarise a completed job without re-uploading |
| `DELETE` | `/api/jobs/{id}` | Delete job and clean up temp files |

**POST `/api/summarize` — JSON body**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `transcript` | string | — | Required. Transcript markdown |
| `title` | string | `null` | Recording title, passed to the model as context |
| `model` | string | `gpt-4o-mini` | Overrides `$SUMMARY_MODEL` |

Returns `503` when no `OPENAI_API_KEY` is configured, `502` when the provider
call fails. Transcripts over ~30 000 characters are summarised map-reduce style
— each chunk is condensed, then the condensations are merged.

**POST `/api/transcribe` — form fields**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `file` | file | — | Required. Any audio or video format |
| `backend` | string | `assemblyai` | `assemblyai` · `openai` · `deepgram` · `whisper` |
| `model` | string | provider default | Model name — see table above |
| `language` | string | `` | BCP-47 code. Empty = auto-detect |
| `title` | string | filename | Markdown heading for the transcript |

---

## Building for distribution

The installers are **fully self-contained** — the target machine needs no
Python, no Node.js and no ffmpeg. Each one ships:

| Component | Source | Size |
|---|---|---|
| CPython 3.14 + all wheels | `uv python install` + `uv pip install` | ~119 MB |
| Static ffmpeg + ffprobe | upstream static builds | ~152 MB |
| Next.js standalone server | `output: "standalone"`, run by Electron's Node | ~33 MB |
| Electron runtime | electron-builder | ~180 MB |

### One command

```bash
uv run scripts/build_installers.py
```

That assembles the runtime, fetches ffmpeg, builds the frontend and runs
electron-builder for **both variants**:

| Variant | Contents | Installer size |
|---|---|---|
| `standard` | AssemblyAI · Deepgram · OpenAI | ~215 MB |
| `offline` | the above **+ local Whisper** | ~610 MB |

Useful flags:

```bash
uv run scripts/build_installers.py --variant standard   # skip the large one
uv run scripts/build_installers.py --targets AppImage   # one format only
uv run scripts/build_installers.py --skip-ffmpeg        # use system ffmpeg
uv run scripts/build_installers.py --clean              # wipe electron/dist first
```

### Per-OS output

Run the same command **on each OS** — see the cross-compilation note below.

| Host | Targets | Artifacts |
|---|---|---|
| Linux (Arch/CachyOS) | `AppImage` `pacman` `deb` `tar.gz` | `transcribe-1.0.0-x86_64.AppImage`, `transcribe-1.0.0-x64.pacman`, … |
| Windows | `nsis` `portable` | `transcribe-1.0.0-x64.exe` (installer + portable) |
| macOS | `dmg` `zip` | `transcribe-1.0.0-arm64.dmg`, `transcribe-1.0.0-x64.dmg` |

Offline-variant artifacts get an `-offline` suffix, e.g.
`transcribe-1.0.0-offline-x86_64.AppImage`.

**Installing on Arch / CachyOS:**

```bash
sudo pacman -U electron/dist/transcribe-1.0.0-x64.pacman
```

For a package built by native Arch tooling instead of electron-builder's fpm
backend — a real `.pkg.tar.zst` you can inspect with `namcap` — use the
included PKGBUILD:

```bash
uv run scripts/build_installers.py --variant standard --targets tar.gz
cd packaging/arch && makepkg -si

VARIANT=offline makepkg -si     # the local-Whisper flavour
```

Both routes install to `/opt/transcribe`, add a `transcribe` launcher on
`PATH`, and register a `.desktop` entry with the app icon.

### Why there is no cross-compilation

Three parts of the bundle are host-specific and cannot be produced from another
OS:

- the CPython tree comes from `uv python install`, which downloads for the host;
- the static ffmpeg builds are per-OS binaries;
- NSIS needs Wine to run on Linux, and DMG creation requires macOS.

So: build Linux artifacts on Linux, `.exe` on Windows, `.dmg` on macOS. The
build script itself is pure Python and runs unchanged on all three.

### Individual steps

```bash
uv run scripts/bundle_runtime.py [--with-whisper]  # → build/runtime/python
uv run scripts/fetch_ffmpeg.py                     # → build/runtime/bin
node scripts/build_frontend.mjs                    # → frontend/.next/standalone
cd electron && npx electron-builder --linux        # → electron/dist
```

### Where the app stores API keys

A packaged install is read-only, so keys live in the per-user config directory,
seeded from `.env.example` on first launch. Reach it from the app menu via
**File → Open API Keys File** (⌘/Ctrl + `,`):

| OS | Path |
|---|---|
| Linux | `~/.config/Transcribe/.env` |
| macOS | `~/Library/Application Support/Transcribe/.env` |
| Windows | `%APPDATA%\Transcribe\.env` |

### Code signing

Artifacts are unsigned. macOS users need to right-click → Open on first launch,
and Windows shows a SmartScreen warning. To sign, set the standard
electron-builder environment variables (`CSC_LINK` / `CSC_KEY_PASSWORD` on
macOS, `WIN_CSC_LINK` / `WIN_CSC_KEY_PASSWORD` on Windows) before building.

---

## Supported formats

| Category | Formats |
|----------|---------|
| Audio | WAV · MP3 · FLAC · OGG · AAC · M4A · WMA |
| Video | MP4 · MOV · AVI · MKV · FLV · WebM · WMV |

Any format supported by ffmpeg works.

---

## Provider limits

| Provider | Max size | Max duration | Notes |
|---|---|---|---|
| AssemblyAI | 5 GB | 10 hours | Async cloud processing |
| Deepgram | 2 GB | — | Synchronous cloud |
| OpenAI | **25 MB** | ~13 min | Use AAI or Deepgram for longer files |
| Whisper (local) | RAM-bound | RAM-bound | Depends on hardware |

---

## License

Personal utilities — use at your own discretion.
