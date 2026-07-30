#!/usr/bin/env python3
"""
Fetch static ffmpeg + ffprobe binaries for the desktop bundle.

Every transcription path runs the input through ffmpeg (normalise to 16 kHz
mono WAV) and ffprobe (duration / stream detection), so shipping them removes
the last "install this yourself" step for end users.

Failure is deliberately non-fatal: if a mirror is down the build still produces
an installer, and the app falls back to whatever ffmpeg is on PATH — the Linux
packages also declare ffmpeg as a package dependency for exactly that case.

Usage:
    uv run scripts/fetch_ffmpeg.py [--out build/runtime/bin] [--force]
"""

from __future__ import annotations

import argparse
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# archive URL -> member matching. `members` maps the output binary name to a
# suffix match inside the archive; `direct` archives hold a single binary.
SOURCES: dict[str, list[dict]] = {
    "linux-x64": [{
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "kind": "tar",
        "members": {"ffmpeg": "/ffmpeg", "ffprobe": "/ffprobe"},
    }],
    "linux-arm64": [{
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
        "kind": "tar",
        "members": {"ffmpeg": "/ffmpeg", "ffprobe": "/ffprobe"},
    }],
    "windows-x64": [{
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "kind": "zip",
        "members": {"ffmpeg.exe": "bin/ffmpeg.exe", "ffprobe.exe": "bin/ffprobe.exe"},
    }],
    "mac-x64": [
        {"url": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip", "kind": "zip", "members": {"ffmpeg": "ffmpeg"}},
        {"url": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip", "kind": "zip", "members": {"ffprobe": "ffprobe"}},
    ],
    "mac-arm64": [
        {"url": "https://www.osxexperts.net/ffmpeg711arm.zip", "kind": "zip", "members": {"ffmpeg": "ffmpeg"}},
        {"url": "https://www.osxexperts.net/ffprobe711arm.zip", "kind": "zip", "members": {"ffprobe": "ffprobe"}},
    ],
}


def host_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    system = "mac" if system == "darwin" else system
    return f"{system}-{arch}"


def download(url: str, dest: Path) -> None:
    print(f"  downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "transcribe-build"})
    with urllib.request.urlopen(request, timeout=180) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    print(f"  -> {dest.stat().st_size / 1024 / 1024:.1f} MB")


def extract(archive: Path, kind: str, members: dict[str, str], out: Path) -> list[str]:
    """Pull the wanted binaries out of the archive, flattening any top dir."""
    found: list[str] = []
    opener = zipfile.ZipFile if kind == "zip" else tarfile.open

    with opener(archive) as bundle:  # type: ignore[operator]
        names = bundle.namelist() if kind == "zip" else bundle.getnames()
        for out_name, suffix in members.items():
            matches = [n for n in names if n.endswith(suffix) and not n.endswith("/")]
            if not matches:
                # Single-binary archives sometimes store a bare name.
                matches = [n for n in names if Path(n).name == out_name]
            if not matches:
                print(f"  ! {out_name} not found in archive", file=sys.stderr)
                continue

            member = sorted(matches, key=len)[0]
            target = out / out_name
            if kind == "zip":
                with bundle.open(member) as source, target.open("wb") as handle:  # type: ignore[union-attr]
                    shutil.copyfileobj(source, handle)
            else:
                source = bundle.extractfile(member)  # type: ignore[union-attr]
                if source is None:
                    continue
                with source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)

            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            found.append(out_name)
            print(f"  extracted {out_name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")

    return found


def verify(out: Path, names: list[str]) -> bool:
    """Run each binary once — a truncated download should not reach an installer."""
    ok = True
    for name in names:
        binary = out / name
        if sys.platform == "win32" and not name.endswith(".exe"):
            continue
        try:
            result = subprocess.run([str(binary), "-version"], capture_output=True, text=True, timeout=30)
            version = result.stdout.splitlines()[0] if result.stdout else "?"
            print(f"  ✓ {name}: {version[:70]}")
        except Exception as exc:  # noqa: BLE001 — any failure means unusable binary
            print(f"  ✗ {name}: {exc}", file=sys.stderr)
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "runtime" / "bin")
    parser.add_argument("--force", action="store_true", help="re-download even if binaries exist")
    parser.add_argument("--platform", dest="plat", default=None, help="override target (default: host)")
    args = parser.parse_args()

    key = args.plat or host_key()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"Fetching ffmpeg/ffprobe for {key}")

    if key not in SOURCES:
        print(f"  no static source configured for {key}; the app will use ffmpeg from PATH")
        return 0

    suffix = ".exe" if key.startswith("windows") else ""
    expected = [f"ffmpeg{suffix}", f"ffprobe{suffix}"]
    if not args.force and all((out / name).exists() for name in expected):
        print("  already present (use --force to re-download)")
        return 0

    obtained: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, spec in enumerate(SOURCES[key]):
            archive = Path(tmp) / f"download-{index}"
            try:
                download(spec["url"], archive)
                obtained += extract(archive, spec["kind"], spec["members"], out)
            except (urllib.error.URLError, OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
                print(f"  ! {spec['url']} failed: {exc}", file=sys.stderr)

    missing = [name for name in expected if not (out / name).exists()]
    if missing:
        print(f"\n⚠ Could not bundle {', '.join(missing)} — the app will fall back to ffmpeg on PATH.")
        print("  Linux packages declare ffmpeg as a dependency; macOS/Windows users would need it installed.")
        return 0

    print("\nVerifying…")
    if not verify(out, obtained):
        print("⚠ A bundled binary did not run; removing it so the app falls back to PATH.", file=sys.stderr)
        for name in expected:
            (out / name).unlink(missing_ok=True)
        return 0

    print(f"\n✓ ffmpeg + ffprobe bundled into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
