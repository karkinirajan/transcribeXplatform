# 03. Testing

```bash
make check               # ruff, pytest, and the desktop shell's tests
uv run pytest -q         # 289 Python tests
cd electron && npm test  # 12 Node tests
```

## Layout

```text
tests/
  test_uploads.py          the file-name, size and form-field rules (hostile names, limits, boundaries)
  test_jobs.py             the registry: expiry, the cap, removal, what finishing does
  test_api_transcribe.py   the upload endpoint, the worker, delete, CORS, and the Host and Origin checks
  test_api_summarize.py, test_summarize.py, test_transcribe_*.py, test_ffmpeg_audio.py, test_media_probe.py, test_format_md.py
                           the providers and the core library (mocked: no network, no ffmpeg run)
  mutation/                the mutation driver and its list
electron/test/
  url-policy.test.js       which URLs may be opened or navigated to
  packaging.test.js        every local module main.js requires is in electron-builder.yml; the window options
```

The upload tests use FastAPI's `TestClient` and replace the worker, so nothing is transcribed; the worker has its own tests with the media tools
replaced. No test needs the network, an API key or ffmpeg.

## Mutation checks

`tests/mutation/mutants.py` holds 47 deliberate bugs in the new Python code, each `(name, file, old text, new text)`: a path separator allowed, a
size limit lifted, an expiry off by one, an origin check removed, the server bound to every interface. The driver applies one at a time and counts it
**killed** if the tests then fail. All 47 are killed. (The first run found five survivors: two missing assertions, two redundant checks that were
simplified, and one equivalent change that is listed at the top of the file.)

```bash
python3 tests/mutation/mutate.py tests/mutation/mutants.py -- uv run pytest -x -q
```

Rules: the suite must be green first (the driver checks); do not edit the tree while it runs; each pattern must occur exactly once.

## What is not tested

The frontend has no tests (it type-checks, lints and builds). The Electron window itself (creating it, starting the servers) is not tested; only
the URL policy and the packaging list are. The provider modules are tested against mocks, never a live service.
