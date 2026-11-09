# 04. Operations

## Running

| Command | Does |
|---|---|
| `make dev` | The desktop app in development (Electron plus both servers). |
| `make dev-api` | The backend alone on `127.0.0.1:8000`. |
| `make dev-web` | The frontend alone on `:3000`. |
| `make check` | ruff, pytest, the desktop shell's tests. |
| `make dist` | The installers (builds the Python runtime, fetches ffmpeg, builds the frontend, runs electron-builder). **Not run by CI.** |

## Before releasing this version

1. **Build and launch the installers** (`make dist`, then run the result): Electron moved from 35 to 45 and `main.js` gained a sandbox, navigation
   guards and a new file (`url-policy.js`); the unit tests cover the logic, not a launched window.
2. Try a real upload on each provider you use: the `openai` and `assemblyai` client libraries each moved a major version.

## Settings

| Variable | Default | |
|---|---|---|
| `TRANSCRIBE_MAX_UPLOAD_MB` | 2048 | Largest accepted upload. |
| `TRANSCRIBE_HOST` | `127.0.0.1` | Bind address of the dev backend. Leave it alone unless something with authentication sits in front. |
| `ASSEMBLYAI_API_KEY`, `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `SUMMARY_MODEL` | | See the README. |

## What to expect

- A job's recording is deleted when it finishes; the transcript stays in memory for an hour, then the job is forgotten (download it first).
- At most 200 jobs are kept; a new upload gets 503 while all are still running.
- A request from a web page, or to a host name other than this machine, is refused (403 / 400): if you reach the API through another name, add it
  deliberately rather than loosening the checks.

## CI

`.github/workflows/ci.yml` runs on every push and pull request to `main`: Python (ruff, pytest, `uv audit`), the frontend on Node 24 and 26
(types, lint, build, audit), and the desktop shell's tests on Node 24 and 26.
