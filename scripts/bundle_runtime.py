#!/usr/bin/env python3
"""
Materialise a self-contained Python runtime for the desktop installers.

Everything is driven by uv:
  * `uv python install`  downloads a relocatable python-build-standalone tree
  * `uv export`          renders the locked dependency set to requirements.txt
  * `uv pip install`     installs those wheels straight into the tree

The result (build/runtime/python) runs on a machine with no Python installed,
which is what lets the Windows/macOS/Linux installers be truly standalone.

Cross-compiling is not supported: python-build-standalone trees are per-OS, so
this must run on the OS you are packaging for. CI does exactly that.

Usage:
    uv run scripts/bundle_runtime.py [--with-whisper] [--out build/runtime]
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSION = "3.14"

# Trimmed after install: none of it is reachable from the API server, and it is
# ~20 MB of every installer.
PRUNE_TREE_DIRS = ("include", "share")
PRUNE_LIB_GLOBS = ("tcl*", "tk*", "itcl*", "thread*", "libtcl*", "libtk*", "sqlite3")
PRUNE_STDLIB_DIRS = ("test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3")
PRUNE_SITE_GLOBS = ("pip", "pip-*", "setuptools", "setuptools-*", "pkg_resources", "wheel", "wheel-*")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def host_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"{ 'mac' if system == 'darwin' else system }-{arch}"


def download_python(cache: Path) -> Path:
    """Fetch a standalone CPython tree via uv and return its root."""
    cache.mkdir(parents=True, exist_ok=True)
    run(["uv", "python", "install", "--install-dir", str(cache), "--no-bin", PYTHON_VERSION])

    # uv lays down `cpython-<full-version>-<platform>` plus a version-alias
    # symlink; take the real directory, never the link.
    candidates = [p for p in cache.iterdir() if p.is_dir() and not p.is_symlink() and p.name.startswith("cpython-")]
    if not candidates:
        raise SystemExit(f"uv did not produce a CPython tree in {cache}")
    return sorted(candidates)[-1]


def tree_layout(tree: Path) -> tuple[Path, Path]:
    """Return (interpreter, site-packages) for a standalone tree, per-OS."""
    if sys.platform == "win32":
        return tree / "python.exe", tree / "Lib" / "site-packages"

    interpreter = tree / "bin" / f"python{PYTHON_VERSION}"
    site_packages = tree / "lib" / f"python{PYTHON_VERSION}" / "site-packages"
    return interpreter, site_packages


def export_requirements(dest: Path, with_whisper: bool) -> Path:
    """Render the locked dependency set — no resolution happens here."""
    cmd = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"]
    if with_whisper:
        cmd += ["--extra", "whisper"]
    print(f"  $ {' '.join(cmd)} > {dest.name}", flush=True)
    result = subprocess.run(cmd, check=True, cwd=ROOT, capture_output=True, text=True)
    dest.write_text(result.stdout, encoding="utf-8")
    return dest


def prune(tree: Path, site_packages: Path) -> None:
    """Drop build headers, Tcl/Tk, the stdlib test suite and packaging tools."""
    def drop(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    for name in PRUNE_TREE_DIRS:
        drop(tree / name)

    lib = tree / "lib"
    if lib.is_dir():
        for pattern in PRUNE_LIB_GLOBS:
            for match in lib.glob(pattern):
                drop(match)

    stdlib = site_packages.parent
    for name in PRUNE_STDLIB_DIRS:
        drop(stdlib / name)
    for match in stdlib.glob("config-*"):
        drop(match)

    for pattern in PRUNE_SITE_GLOBS:
        for match in site_packages.glob(pattern):
            drop(match)

    for cache_dir in tree.rglob("__pycache__"):
        # Stdlib caches speed up startup; test/vendor caches are dead weight.
        if "site-packages" in cache_dir.parts:
            shutil.rmtree(cache_dir, ignore_errors=True)


def directory_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())
    return round(total / 1024 / 1024, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "runtime",
                        help="output directory (default: build/runtime)")
    parser.add_argument("--with-whisper", action="store_true",
                        help="include faster-whisper for offline transcription (adds ~400 MB)")
    parser.add_argument("--keep-cache", action="store_true",
                        help="keep the downloaded CPython tree for faster rebuilds")
    args = parser.parse_args()

    out = args.out.resolve()
    cache = ROOT / "build" / ".python-cache"
    target_python = out / "python"

    print(f"Bundling Python {PYTHON_VERSION} runtime for {host_tag()}")
    print(f"  output:  {target_python}")
    print(f"  whisper: {'yes' if args.with_whisper else 'no (cloud providers only)'}")

    print("\n[1/5] Downloading standalone CPython via uv…")
    source_tree = download_python(cache)
    print(f"      -> {source_tree.name}")

    print("\n[2/5] Copying interpreter into the bundle…")
    if target_python.exists():
        shutil.rmtree(target_python)
    target_python.parent.mkdir(parents=True, exist_ok=True)
    # symlinks=True keeps python3 -> python3.14 relative links intact.
    shutil.copytree(source_tree, target_python, symlinks=True)

    interpreter, site_packages = tree_layout(target_python)
    if not interpreter.exists():
        raise SystemExit(f"interpreter missing after copy: {interpreter}")

    print("\n[3/5] Exporting locked requirements…")
    requirements = export_requirements(out / "requirements-bundle.txt", args.with_whisper)
    pinned = sum(1 for line in requirements.read_text().splitlines() if "==" in line)
    print(f"      -> {pinned} pinned packages")

    print("\n[4/5] Installing wheels into the interpreter…")
    run([
        "uv", "pip", "install",
        "--python", str(interpreter),
        "--target", str(site_packages),
        "--only-binary=:all:",
        "-r", str(requirements),
    ], cwd=ROOT)

    print("\n[5/5] Pruning and verifying…")
    prune(target_python, site_packages)

    # Import the real dependency surface with an empty environment — this is the
    # same isolation the packaged app gets.
    check = subprocess.run(
        [str(interpreter), "-c",
         "import fastapi, uvicorn, assemblyai, openai, httpx, dotenv, multipart, aiofiles; print('ok')"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"} if sys.platform != "win32" else None,
    )
    if check.returncode != 0 or "ok" not in check.stdout:
        print(check.stdout, check.stderr, file=sys.stderr)
        raise SystemExit("bundled runtime failed its import check")

    if args.with_whisper:
        whisper_check = subprocess.run([str(interpreter), "-c", "import faster_whisper; print('ok')"],
                                       capture_output=True, text=True)
        if whisper_check.returncode != 0:
            print(whisper_check.stderr, file=sys.stderr)
            raise SystemExit("faster-whisper missing from the bundled runtime")

    manifest = {
        "python_version": PYTHON_VERSION,
        "platform": host_tag(),
        "whisper": args.with_whisper,
        "packages": pinned,
        "size_mb": directory_size_mb(target_python),
    }
    (out / "runtime.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if not args.keep_cache:
        shutil.rmtree(cache, ignore_errors=True)

    print(f"\n✓ Runtime ready: {manifest['size_mb']} MB, {pinned} packages, import check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
