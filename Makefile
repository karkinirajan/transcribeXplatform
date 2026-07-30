.PHONY: install install-whisper dev dev-api dev-web test lint \
        runtime ffmpeg frontend dist dist-standard dist-offline clean help

# Python tooling is uv end to end; `uv sync` creates .venv from uv.lock.
UV ?= uv

help:
	@echo "Development"
	@echo "  make install          Install Python, frontend and Electron dependencies"
	@echo "  make install-whisper  ...plus faster-whisper for offline transcription"
	@echo "  make dev              Run the desktop app (API + Next.js + Electron)"
	@echo "  make dev-api          Run only the FastAPI backend on :8000"
	@echo "  make dev-web          Run only the Next.js frontend on :3000"
	@echo "  make test             Run the pytest suite"
	@echo ""
	@echo "Packaging (builds for the OS you run it on)"
	@echo "  make dist             Both installer variants for this OS"
	@echo "  make dist-standard    Cloud providers only (~215 MB)"
	@echo "  make dist-offline     Includes local Whisper (~610 MB)"
	@echo "  make runtime          Just the bundled Python runtime"
	@echo "  make ffmpeg           Just the static ffmpeg/ffprobe binaries"
	@echo "  make frontend         Just the Next.js standalone bundle"
	@echo "  make clean            Remove build/ and electron/dist/"

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

install:
	$(UV) sync
	cd frontend && npm install
	cd electron && npm install

install-whisper:
	$(UV) sync --extra whisper
	cd frontend && npm install
	cd electron && npm install

dev:
	cd electron && npm run dev

dev-api:
	$(UV) run python backend/main.py

dev-web:
	cd frontend && npm run dev

test:
	$(UV) run pytest -v

# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

runtime:
	$(UV) run scripts/bundle_runtime.py

ffmpeg:
	$(UV) run scripts/fetch_ffmpeg.py

frontend:
	node scripts/build_frontend.mjs

dist:
	$(UV) run scripts/build_installers.py

dist-standard:
	$(UV) run scripts/build_installers.py --variant standard

dist-offline:
	$(UV) run scripts/build_installers.py --variant offline

clean:
	rm -rf build electron/dist frontend/.next
