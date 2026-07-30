#!/usr/bin/env python3
"""
Build Transcribe desktop installers.

Runs the whole pipeline: bundle a self-contained Python runtime, fetch static
ffmpeg binaries, build the Next.js standalone server, then hand everything to
electron-builder.

Two variants are produced:
  standard  cloud providers only (AssemblyAI / Deepgram / OpenAI)  ~200 MB
  offline   the above plus local Whisper (faster-whisper)          ~600 MB

This script runs on Linux, Windows and macOS. It always builds for the OS it is
running on: the bundled CPython tree, the ffmpeg binaries, the NSIS installer
and the DMG are all host-specific, so there is no cross-compilation path. To get
all three platforms, run it once on each.

    uv run scripts/build_installers.py                      # both variants, host OS
    uv run scripts/build_installers.py --variant standard   # just the small one
    uv run scripts/build_installers.py --targets AppImage pacman
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELECTRON_DIR = ROOT / "electron"
DIST_DIR = ELECTRON_DIR / "dist"
RUNTIME_DIR = ROOT / "build" / "runtime"

VARIANTS = {
    "standard": {"whisper": False, "suffix": ""},
    "offline": {"whisper": True, "suffix": "-offline"},
}

# electron-builder's platform flag, keyed by host OS.
HOST_FLAG = {"linux": "--linux", "windows": "--win", "darwin": "--mac"}

DEFAULT_TARGETS = {
    "linux": ["AppImage", "pacman", "deb", "tar.gz"],
    "windows": ["nsis", "portable"],
    "darwin": ["dmg", "zip"],
}


def host_os() -> str:
    system = platform.system().lower()
    if system not in HOST_FLAG:
        raise SystemExit(f"Unsupported build host: {platform.system()}")
    return system


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    printable = " ".join(str(c) for c in cmd)
    print(f"\n  $ {printable}", flush=True)
    result = subprocess.run(cmd, cwd=cwd, env=env, shell=False)
    if result.returncode != 0:
        raise SystemExit(f"\n✗ Command failed ({result.returncode}): {printable}")


def npx(*args: str) -> list[str]:
    """electron-builder is a local devDependency; go through the npm bin dir."""
    binary = "electron-builder.cmd" if os.name == "nt" else "electron-builder"
    local = ELECTRON_DIR / "node_modules" / ".bin" / binary
    if local.exists():
        return [str(local), *args]
    return ["npx", "--no-install", "electron-builder", *args]


def ensure_electron_deps() -> None:
    if (ELECTRON_DIR / "node_modules" / ".bin").exists():
        return
    print("\nInstalling electron build tooling…")
    run(["npm", "install", "--no-audit", "--no-fund"], cwd=ELECTRON_DIR)


def assemble(variant: str, skip_ffmpeg: bool, skip_frontend: bool) -> None:
    """Materialise everything that goes inside the app bundle."""
    whisper = VARIANTS[variant]["whisper"]

    print(f"\n{'=' * 70}\n  Assembling '{variant}' bundle\n{'=' * 70}")

    runtime_cmd = [sys.executable, str(ROOT / "scripts" / "bundle_runtime.py")]
    if whisper:
        runtime_cmd.append("--with-whisper")
    run(runtime_cmd, cwd=ROOT)

    if skip_ffmpeg:
        print("\n  (skipping ffmpeg fetch)")
    else:
        run([sys.executable, str(ROOT / "scripts" / "fetch_ffmpeg.py")], cwd=ROOT)

    # The frontend is identical across variants, so build it once.
    standalone = ROOT / "frontend" / ".next" / "standalone" / "server.js"
    if skip_frontend or standalone.exists():
        print(f"\n  (frontend bundle already built at {standalone.parent})")
    else:
        run(["node", str(ROOT / "scripts" / "build_frontend.mjs")], cwd=ROOT)


def package(variant: str, targets: list[str], publish_never: bool = True) -> list[Path]:
    """Run electron-builder and return the artifacts it produced."""
    system = host_os()
    suffix = VARIANTS[variant]["suffix"]

    before = set(DIST_DIR.glob("*")) if DIST_DIR.exists() else set()

    args = [HOST_FLAG[system], *targets]
    # Distinguish the two variants in the filename.
    args += ["-c.artifactName=${name}-${version}" + suffix + "-${arch}.${ext}"]
    if publish_never:
        args += ["--publish", "never"]

    env = os.environ.copy()
    # Nothing here is code-signed; make that explicit rather than failing late.
    env.setdefault("CSC_IDENTITY_AUTO_DISCOVERY", "false")

    print(f"\n{'=' * 70}\n  Packaging '{variant}' → {', '.join(targets)}\n{'=' * 70}")
    run(npx(*args), cwd=ELECTRON_DIR, env=env)

    after = set(DIST_DIR.glob("*")) if DIST_DIR.exists() else set()
    return sorted(p for p in (after - before) if p.is_file())


def human_size(path: Path) -> str:
    return f"{path.stat().st_size / 1024 / 1024:.0f} MB"


def main() -> int:
    system = host_os()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=[*VARIANTS, "both"], default="both",
                        help="which bundle(s) to build (default: both)")
    parser.add_argument("--targets", nargs="+", default=None,
                        help=f"electron-builder targets (default for {system}: {' '.join(DEFAULT_TARGETS[system])})")
    parser.add_argument("--skip-ffmpeg", action="store_true", help="do not bundle ffmpeg/ffprobe")
    parser.add_argument("--skip-frontend", action="store_true", help="reuse the existing Next.js bundle")
    parser.add_argument("--clean", action="store_true", help="wipe electron/dist first")
    args = parser.parse_args()

    targets = args.targets or DEFAULT_TARGETS[system]
    variants = list(VARIANTS) if args.variant == "both" else [args.variant]

    print(f"Transcribe installer build")
    print(f"  host:     {platform.system()} {platform.machine()}")
    print(f"  variants: {', '.join(variants)}")
    print(f"  targets:  {', '.join(targets)}")

    if args.clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)

    ensure_electron_deps()

    started = time.time()
    produced: dict[str, list[Path]] = {}

    for variant in variants:
        assemble(variant, args.skip_ffmpeg, args.skip_frontend)
        produced[variant] = package(variant, targets)

    # The offline runtime is the last one written; leaving it behind would make
    # a subsequent `npm run build` silently ship the 600 MB variant.
    if len(variants) > 1 and RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)

    elapsed = time.time() - started
    print(f"\n{'=' * 70}\n  Done in {elapsed / 60:.1f} min\n{'=' * 70}")

    total = 0
    for variant, artifacts in produced.items():
        print(f"\n{variant}:")
        if not artifacts:
            print("  (no new files — check the electron-builder output above)")
        for artifact in artifacts:
            print(f"  {artifact.name:<52} {human_size(artifact):>8}")
            total += 1

    if not total:
        return 1

    print(f"\n{total} artifact(s) in {DIST_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
