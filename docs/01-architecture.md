# 01. Architecture

Four pieces that share one Python core:

```text
CLI  ──────────────┐
                   ├─► utilities_data/transcribe/   probe → ffmpeg (16 kHz mono WAV) → provider → speaker turns → Markdown
FastAPI backend ───┘        providers: AssemblyAI · OpenAI · Deepgram · local Whisper;  summarize.py (map-reduce)
   ▲
   │ /api/*   (Next.js rewrites it, so the browser sees one origin)
Next.js frontend ◄── Electron window (the desktop app: starts the backend and the frontend on 127.0.0.1 and loads the page)
```

## The backend (`backend/`)

| Module | Does |
|---|---|
| `main.py` | The endpoints, the worker that runs a job, the Host and Origin checks. |
| `uploads.py` | What an upload may be: the stored file name, the size cap, the free-text form fields. |
| `jobs.py` | The in-memory job registry: finished jobs expire (1 hour), at most 200 are kept, and a finished job's recording is deleted. |

A transcription is a thread-pool job: the upload is saved under a fresh temporary directory, normalised to WAV, sent to the chosen provider,
turned into speaker turns and Markdown, kept **in memory** as the job's transcript, and the temporary directory (which holds the recording) is
removed as soon as the job finishes, successfully or not.

## Who may call the API

It listens on `127.0.0.1:8000` and has no sign-in, because it is meant to be used only by the app on the same machine. Two checks keep other
things on that machine's network path out (see [02 Security](02-security.md)): the `Host` header must name this machine, and a write that carries
an `Origin` header must come from the app's own origin.

## The desktop shell (`electron/`)

`main.js` starts the Python runtime and the Next.js standalone server, waits for both, and opens one window on `http://127.0.0.1:3000`.
`url-policy.js` decides which URLs the window may navigate to or hand to the operating system. electron-builder packs only the files listed in
`electron-builder.yml`; a test fails if `main.js` requires a local file that is not listed.
