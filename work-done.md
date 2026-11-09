# Work done

What this repository was, what was changed, and what still needs a person. Branch: `chore/modernize` (local, nothing pushed).
Start point: `5177c35`.

## At a glance

- **Was:** a transcription tool with four pieces (a FastAPI backend, a Next.js frontend, an Electron desktop app, a CLI) and 148 tests. It was
  already in good shape (uv, a lockfile, installers), but its API had real holes: **an upload's file name was joined onto a temporary
  directory unchanged, so a name like `../../x.mp3` wrote the uploaded bytes outside it**; any web page the user visited could upload a file
  to the local API and spend their transcription credit (a cross-site `POST` needs no CORS permission to be sent, and DNS rebinding could read
  the answers); `make dev-api` listened on every network interface with no sign-in; uploads were unlimited and recordings stayed on disk;
  and the desktop window handed **any** URL to the operating system. Its dependencies included an out-of-support Electron (35) and 48
  known advisories across the two Node packages.
- **Now:** all fixed and tested; 289 Python tests and 12 Node tests; 47 deliberate bugs that the suite fails for; a ruff lint gate (there was none:
  the Makefile named a `lint` target that did not exist); every dependency on its latest release with the three audits clean; CI; README
  extended, `VERSIONS.md` and four docs chapters added.
- **Needs a person:** **build and launch the installers** before releasing (Electron moved from 35 to 45; only the logic is tested here), try a real
  upload on each provider (the `openai` and `assemblyai` libraries each moved a major version), and push.

## Verified

Run on the final tree, 2026-11-09:

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | pass (new gate; the rule set is in `pyproject.toml`; 79 findings fixed, none suppressed beyond the documented per-file ignores) |
| Python tests | `uv run pytest -q` | 289 passed |
| Desktop shell tests | `cd electron && npm test` | 12 passed |
| Mutation | `tests/mutation/mutate.py` | 47 of 47 killed, on a green baseline (a first run left 5 survivors: 2 missing assertions added, 2 redundant checks simplified, 1 equivalent change listed) |
| Frontend | `tsc --noEmit`, `npm run lint`, `npm run build` | pass (the new react-hooks rule flagged a model reset done in an effect; it is now done in the selection handler) |
| Audits | `uv audit`; `npm audit` in `frontend/` and `electron/` | none known; 0; 0 (were: a `setuptools` advisory; 19 incl. 1 critical; 29 incl. 2 critical and 22 high) |
| Secrets | pattern scan of the tree and all 7 commits | none found (a pattern scan, counts only; `.env*` files were not read; not a guarantee) |
| Formatting | | not changed: ruff's formatter was not applied to the existing code |

**Not verified:** the installers (`make dist`) and a launched Electron window; any real provider (AssemblyAI, OpenAI, Deepgram, local Whisper);
a real ffmpeg run (the tests replace it); the frontend in a browser against a live backend.

## Findings and fixes

| Finding | Fix |
|---|---|
| **Upload file name used as a path** (`temp_dir / file.filename`): arbitrary-location write of attacker-chosen bytes to any `*.mp3`/`*.mp4`-style path | `backend/uploads.safe_upload_name`: last segment only, safe characters, bounded, validated extension; tests prove the result never leaves the directory |
| **Cross-site requests and DNS rebinding** could use the user's provider keys through the local API | `Host` must be this machine; writes with an `Origin` from anywhere else get 403; CORS narrowed to the methods and header used |
| `make dev-api` bound `0.0.0.0` with no authentication | Binds `127.0.0.1` (`TRANSCRIBE_HOST` overrides) |
| Unlimited upload size; the copy blocked the event loop; the recording stayed on disk until `DELETE`; jobs never left memory | 2 GiB cap counted as bytes arrive (413, partial file deleted), copy in a thread, recording deleted when the job finishes, finished jobs expire after an hour, at most 200 kept |
| `language`, `model`, `title` unvalidated | Validated (400) before anything is stored |
| **`shell.openExternal(url)` on any URL** from the window | Only http(s); navigation away from the app is blocked; sandbox on; permissions denied; webviews refused |
| `url-policy.js` would not have been packaged (electron-builder packs only listed files) | Added to the list, with a test that fails if `main.js` requires any local file that is not listed |
| No lint gate (the Makefile named `lint` but had no such target); 79 style and bug-risk findings; 10 `raise` inside `except` without chaining | ruff, configured; findings fixed; exceptions chained |
| Out-of-support Electron 35; 48 advisories across the Node packages | Electron 45, electron-builder 26, current frontend; audits 0 |

Details: [docs/02-security.md](docs/02-security.md).

## Changes, file by file

### Source

| File | Was | Now |
|---|---|---|
| `backend/uploads.py` (new) | none | File-name, size and form-field rules |
| `backend/jobs.py` | Unbounded in-memory store | Expiry, cap, `finish_job`, `remove_job` |
| `backend/main.py` | Raw file name, no limit, `0.0.0.0`, `get_event_loop`, wildcard CORS | See above |
| `electron/url-policy.js` (new), `electron/main.js`, `electron/electron-builder.yml` | any URL opened externally | Policy, navigation guards, sandbox, packaging entry |
| `frontend/app/components/TranscribeApp.tsx` | model reset in an effect | in the selection handler |
| `utilities_data/transcribe/*.py`, `scripts/build_installers.py`, tests | `Optional[...]`, unsorted imports, unchained re-raises, a few unused names | Modern annotations, sorted imports, `raise ... from`, no behaviour change |
| `Makefile` | `lint` declared but missing | `lint`, `check`, `test-electron` |

### Configuration and tooling

| File | Was | Now |
|---|---|---|
| `pyproject.toml`, `uv.lock` | no lint config | ruff configuration and dev dependency; every package at its latest release |
| `frontend/package.json`, `electron/package.json` (+ locks) | Old and exact versions | See [VERSIONS.md](VERSIONS.md); `engines.node >=24`; `minimatch` overrides; electron `test` script |
| `.nvmrc` (new) | | `26` |
| `.github/workflows/ci.yml` (new) | none | Python (ruff, pytest, `uv audit`), frontend and desktop shell on Node 24 and 26 |
| `tests/` | 148 tests | 289, plus `tests/mutation/` and `electron/test/` |

### Docs

`README.md` extended (limits and status codes, the loopback binding, the new settings, test counts, a docs table; the rest is unchanged).
`VERSIONS.md`, `docs/01` to `04` and this file are new. `.env.example` was not read or changed (by rule).

## What a person might want to do

1. **Build and launch the installers** (`make dist`) and click through the window: Electron 35 → 45 and the new sandbox and guards are untested
   as a running app.
2. **Try one real upload per provider you use**: `openai` 2 → 3 and `assemblyai` 0.64 → 1.8 are major releases (the mocked tests pass).
3. If the dev backend was ever run on a shared network (`make dev-api` bound every interface), treat the provider keys it could reach as exposed
   and rotate them.
4. **Push** when satisfied: `git push -u origin chore/modernize` (not done here).

## Known and left alone

- The API has no sign-in (it trusts the machine); job ids are the only protection of a job's transcript.
- Provider error text can reach the page.
- The frontend has no tests; the Electron window itself is not tested.
- TypeScript 7 (the linter does not support it yet).
