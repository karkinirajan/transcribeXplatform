# 02. Security

What a review of the existing code found and fixed, how to configure what needs configuring, and what was left. Each fix has tests, and the
new Python code was mutation-checked ([03 Testing](03-testing.md)).

## What was fixed

### An upload could write a file anywhere the user could (path traversal)

`POST /api/transcribe` joined the browser-supplied file name onto its temporary directory unchanged:
`input_path = temp_dir / file.filename`. A name such as `../../home/me/Music/song.mp3` (the extension check only looks at the end) wrote the
uploaded bytes to that path: an arbitrary-location write of attacker-chosen content to any file whose name ends in an audio or video extension.
The stored name now comes from `uploads.safe_upload_name`: only the last path segment is kept (either kind of separator), anything outside
letters, digits, dot, dash, underscore and space becomes an underscore, leading dots are dropped, the stem is bounded, and the extension is the
validated one. Tests cover the hostile names and check that the result joined onto a directory never leaves it.

### Any web page could use the user's transcription account (CSRF and DNS rebinding)

The API is on `127.0.0.1`, but a web page the user visits can still send requests to it. A cross-site `POST` with a multipart body needs no CORS
permission to be *sent*, so any site could upload a file and spend the user's AssemblyAI, OpenAI or Deepgram credit; and a page on an attacker's
domain that is made to resolve to `127.0.0.1` ("DNS rebinding") could read the answers too. Now the `Host` header must be `localhost`,
`127.0.0.1` or `[::1]` (Starlette's `TrustedHostMiddleware`), and a `POST`/`PUT`/`PATCH`/`DELETE` carrying an `Origin` header from anywhere but
the app's own origins is refused with 403 before anything is read. CORS now allows only `GET`, `POST` and `DELETE` and the `Content-Type` header.

### The development server listened on every network interface

`make dev-api` ran `uvicorn` on `0.0.0.0`, so anyone on the same network could use the API (and the owner's provider keys) with no sign-in. It
binds `127.0.0.1` now; `TRANSCRIBE_HOST` overrides it for someone who puts authentication in front. (The desktop app already used `127.0.0.1`.)

### Unbounded uploads, and recordings that stayed on disk

There was no size limit, so one request could fill the disk; it is now 2 GiB (`TRANSCRIBE_MAX_UPLOAD_MB`), counted as the bytes arrive, refused
with 413, and the partial file is deleted. The copy runs off the event loop. A finished job's recording stayed in the temporary directory until
the client called `DELETE` (which also left the job in memory forever); the recording is now deleted when the job finishes, finished jobs expire
after an hour, and at most 200 jobs are kept (a new upload is refused with 503 when all are still running).

### Free-text fields

`language`, `model` and `title` went straight to the provider calls. They are validated (a language code, a model name from a restricted
alphabet and 100 characters, a printable title of at most 200 characters) and refused with 400 before anything is stored.

### Desktop window

`setWindowOpenHandler` passed **any** URL to `shell.openExternal`, which hands it to the operating system: a link whose scheme is `file:`,
`smb:`, `ms-msdt:` and so on starts whatever handles it. Only `http:` and `https:` links are opened now (`electron/url-policy.js`, tested). The
window also refuses to navigate away from the local app (`will-navigate`, `will-redirect`; other links open in the browser), is sandboxed
(`sandbox: true`), denies every permission request and refuses webviews. Dependencies: Electron 35 (out of support) to 45; `npm audit` 29 → 0.

## Configuration

- `TRANSCRIBE_MAX_UPLOAD_MB` (default 2048), `TRANSCRIBE_HOST` (default `127.0.0.1`), `TRANSCRIBE_CONFIG_DIR` (set by the desktop app).
- Provider keys stay in `.env` or the per-user config directory; the repository was scanned for credentials (working tree and history; a pattern
  scan, `.env*` files were not read): none found.

## Known and left alone

- **No sign-in.** The API trusts whoever is on the machine. The Host and Origin checks stop other websites; they do not stop another program
  running as the same user.
- **Job ids are random UUIDs and are the only protection of a job's transcript** (anyone who can call the API and knows an id can read it).
- Provider error text can reach the page (`job.error`, summary errors): useful to the user, and it is their own account.
- **The packaged desktop app was not built or launched here** (see [VERSIONS.md](../VERSIONS.md)): Electron moved ten major versions.
- No end-to-end test with real providers; the provider modules are tested against mocks.
