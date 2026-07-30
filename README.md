# Transcribe

Audio and video transcription with speaker identification and one-click AI
summaries — as a **CLI**, a **web app**, and a **self-contained desktop app**
for Linux, Windows and macOS.

## Providers

| Provider | Price | Speaker ID | Languages |
|---|---|---|---|
| [AssemblyAI](https://assemblyai.com) | $0.17/hr · **$50 free credits** | ✅ with names | 99+ |
| [Deepgram Nova-3](https://deepgram.com) | $0.26/hr · **12 000 min/yr free** | ✅ labels | 40+ |
| [OpenAI](https://platform.openai.com) | $0.18–0.36/hr | ✗ | 99+ |
| Whisper (local) | **free, offline** | ✗ | 99+ |

Any file is normalised to 16 kHz mono WAV with ffmpeg first, so anything ffmpeg
reads works. Output is `[HH:MM:SS] Speaker: text` markdown.

## Install

**Users:** grab an installer from
[Releases](https://github.com/karkinirajan/transcribeXplatform/releases) —
Python, ffmpeg and Node are bundled, so there is nothing else to install.
Pick `standard` (~215 MB, cloud providers) or `offline` (~610 MB, adds local
Whisper).

**Developers:**

```bash
git clone https://github.com/karkinirajan/transcribeXplatform
cd transcribeXplatform
cp .env.example .env      # add at least one API key
make install              # uv sync + npm install
```

Python tooling is [uv](https://docs.astral.sh/uv/); `uv sync --extra whisper`
adds offline transcription. ffmpeg is needed only when running from source.

## Run

```bash
make dev        # desktop app (Electron + both servers)
make dev-api    # backend only, :8000
make dev-web    # frontend only, :3000
make test       # 148 tests
```

CLI:

```bash
transcribe audio.mp3
transcribe interview.mp4 --backend deepgram --language es
transcribe meeting.mp4 --backend whisper --model small -o out.md
```

| Backend | Models |
|---|---|
| `assemblyai` | Universal (fixed) |
| `deepgram` | `nova-3` · `nova-2` · `enhanced` · `base` |
| `openai` | `gpt-4o-mini-transcribe` · `gpt-4o-transcribe` · `whisper-1` |
| `whisper` | `tiny` · `base` · `small` · `medium` · `large-v3-turbo` |

## Configuration

Set keys in `.env` (dev) or via the app menu **File → Open API Keys File**
(packaged — the install directory is read-only, so keys live per-user in
`~/.config/Transcribe/.env`, `~/Library/Application Support/Transcribe/.env`,
or `%APPDATA%\Transcribe\.env`).

```env
ASSEMBLYAI_API_KEY=
DEEPGRAM_API_KEY=
OPENAI_API_KEY=      # also powers the Summarize button
# SUMMARY_MODEL=gpt-4o-mini
```

`GET /api/health` reports which providers are ready.

## Summaries

Every finished transcript gets a **Summarize** button producing an overview,
key points, decisions and action items. Transcripts beyond ~30 000 characters
are summarised map-reduce style — each chunk condensed, then merged — so a
90-minute meeting works. Summaries are included in `.md`/`.txt` downloads.

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Provider readiness |
| `POST` | `/api/transcribe` | Upload file, start job → `{job_id}` |
| `GET` | `/api/jobs/{id}` | Poll status |
| `GET` | `/api/jobs/{id}/events` | SSE progress stream |
| `GET` | `/api/jobs/{id}/transcript` | Completed transcript |
| `POST` | `/api/summarize` | `{transcript, title?, model?}` → summary |
| `POST` | `/api/jobs/{id}/summary` | Summarise a completed job |
| `DELETE` | `/api/jobs/{id}` | Delete job, clean temp files |

`/api/transcribe` form fields: `file` (required), `backend`, `model`,
`language`, `title`. Summarize returns `503` with no key, `502` on provider
failure.

## Building installers

```bash
uv run scripts/build_installers.py              # both variants, host OS
uv run scripts/build_installers.py --variant standard
uv run scripts/build_installers.py --targets AppImage
```

Each installer bundles a relocatable CPython (materialised with
`uv python install` + `uv pip install`), static ffmpeg/ffprobe, and the Next.js
standalone server run by Electron's own Node.

| Host | Artifacts |
|---|---|
| Linux | `.AppImage` · `.pacman` · `.deb` · `.tar.gz` |
| Windows | `.exe` (NSIS + portable) |
| macOS | `.dmg` · `.zip` (arm64 + x64) |

**Run it on each OS** — there is no cross-compilation path: the CPython tree is
downloaded per-host, ffmpeg statics are per-OS, NSIS needs Wine and DMG needs
macOS. The script itself is pure Python and runs unchanged on all three.
Intel macOS cannot take the offline variant (onnxruntime ships no macOS x86_64
wheels).

Arch/CachyOS:

```bash
sudo pacman -U electron/dist/transcribe-1.0.0-x64.pacman
# or a native package built by makepkg:
cd packaging/arch && makepkg -si
```

Artifacts are unsigned — macOS needs right-click → Open on first launch. Set
`CSC_LINK`/`WIN_CSC_LINK` before building to sign.

## Layout

```
utilities_data/transcribe/  Core library: probe, ffmpeg, providers, summarize
backend/                    FastAPI — endpoints, job runner, SSE
frontend/                   Next.js 16 + Tailwind
electron/                   Desktop shell + electron-builder config
scripts/                    Runtime bundler, ffmpeg fetch, installer build
packaging/arch/             Native Arch PKGBUILD
tests/                      148 pytest tests
```

## Limits

| Provider | Max size | Max duration |
|---|---|---|
| AssemblyAI | 5 GB | 10 hours |
| Deepgram | 2 GB | — |
| OpenAI | **25 MB** | ~13 min |
| Whisper (local) | RAM-bound | RAM-bound |

## License

MIT
