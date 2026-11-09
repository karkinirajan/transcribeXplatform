# Versions

What this project runs on, and why, as of 2026-11-09. Everything below was read from the lockfiles, the environments or the registries
on that day; nothing is quoted from memory.

## Runtimes

| | Version | Notes |
|---|---|---|
| Python | **3.14** (`.python-version`); `requires-python >=3.12` | uv installs it. The bundled installers carry their own runtime. |
| Node.js | **26** (`.nvmrc`); `engines.node >=24` (frontend and electron) | The desktop app runs the frontend with Electron's built-in Node, so installers need no Node. |
| uv | 0.13 | `uv.lock` is the Python lockfile. |

## Python (`uv.lock`)

| Package | Locked | Was | Notes |
|---|---|---|---|
| fastapi | 0.162.2 | 0.141.1 | |
| starlette | 1.10.0 | 1.3.1 | |
| uvicorn | 0.54.0 | 0.52.0 | |
| python-multipart | 0.33 | 0.32 | |
| openai | 3.48.0 | 2.50.0 | A major release; the provider code and its mocked tests pass. Not exercised against the live API. |
| assemblyai | 1.8.2 | 0.64.32 | A major release; mocked tests pass, not exercised against the live API. |
| pydantic | 2.14.3 | 2.13.4 | |
| httpx | 0.28.1 | 0.28.1 | |
| pytest | 9.2.0 | 9.1.1 | dev |
| **ruff** | 0.17.4 | (new) | dev; configured in `pyproject.toml` |

`uv lock --upgrade` moved every package to its latest release. `uv audit`: no known vulnerabilities (the baseline lock carried a
`setuptools` advisory; `setuptools` is no longer in the lock).

## Frontend (`frontend/`)

| Package | Installed | Was |
|---|---|---|
| next | 16.4.5 | 16.2.4 (exact) |
| react / react-dom | 19.3.1 | 19.2.4 (exact) |
| typescript | **6.0.3** | ^5 (`typescript-eslint` supports `<6.1`, so 7.0.2 is not usable yet) |
| eslint / eslint-config-next | 10.14.0 / 16.4.5 | ^9 / 16.2.4 |
| tailwindcss, @tailwindcss/postcss | 4.3.5 | 4.2.3 |

`npm audit`: **19 vulnerabilities (1 critical, 8 high) → 0** (upgrades, `npm audit fix` for transitive packages, `minimatch` override).

## Desktop shell (`electron/`)

| Package | Installed | Was | Notes |
|---|---|---|---|
| electron | **45.2.3** | ^35.0.0 (35.7.5) | **Ten majors.** 35 is out of Electron's support window (it no longer gets Chromium security fixes). The shell uses only basic APIs, and its logic is tested; **the packaged app was not built or launched here**: do that before releasing (`make dist`). |
| electron-builder | 26.18.0 | ^25 | |
| concurrently, wait-on | 10.0.7, 9.x | ^8, ^8 | dev scripts only |

`npm audit`: **29 vulnerabilities (2 critical, 22 high) → 0**.

## Left alone

TypeScript 7 (see above). Re-check with `npm outdated` (both Node packages) and `uv lock --upgrade` when touching dependencies.
