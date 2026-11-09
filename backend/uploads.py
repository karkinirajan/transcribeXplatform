"""Rules for what the upload endpoint accepts: the stored file name, the size, and the free-text form fields.

The browser tells the server a file name, and the server used to join it onto a temporary directory unchanged, so a name such as
``../../home/me/Music/song.mp3`` wrote the uploaded bytes outside it. The size was unlimited, so one request could fill the disk.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import BinaryIO

# 2 GiB by default (an hour of lossless audio is well under that); TRANSCRIBE_MAX_UPLOAD_MB overrides it.
DEFAULT_MAX_UPLOAD_MB = 2048
MAX_FILENAME_STEM = 100
MAX_TITLE = 200
MAX_MODEL = 100

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})?$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class UploadTooLargeError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"The file is larger than the {limit // (1024 * 1024)} MB limit.")
        self.limit = limit


def max_upload_bytes(env: dict[str, str] | None = None) -> int:
    raw = (env if env is not None else os.environ).get("TRANSCRIBE_MAX_UPLOAD_MB", "")
    try:
        megabytes = int(raw) if raw.strip() else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    return max(1, megabytes) * 1024 * 1024


def safe_upload_name(filename: str | None, suffix: str) -> str:
    """A file name that can only ever name a file inside the directory it is joined onto.

    Only the last path segment is kept (browsers and clients on Windows send either kind of separator), anything outside letters,
    digits, dot, dash, underscore and space becomes an underscore, leading dots are dropped, the stem is bounded, and the extension is
    the validated one. The result never contains a separator, never starts with a dot or a dash, and is never empty.
    """
    raw = filename or ""
    last = PurePosixPath(PureWindowsPath(raw).name).name
    stem = last[: -len(PurePosixPath(last).suffix)] if PurePosixPath(last).suffix else last
    stem = _UNSAFE.sub("_", stem)[:MAX_FILENAME_STEM].strip(" ._-")
    return f"{stem or 'upload'}{suffix}"


def copy_limited(source: BinaryIO, destination: BinaryIO, max_bytes: int, chunk_size: int = 1024 * 1024) -> int:
    """Copies source to destination, stopping with UploadTooLargeError as soon as more than max_bytes have been read."""
    total = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            return total
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(max_bytes)
        destination.write(chunk)


def clean_language(value: str | None) -> str | None:
    """A language code such as ``en`` or ``en-US``, or None for 'detect'. Anything else is refused with ValueError."""
    text = (value or "").strip()
    if not text:
        return None
    if not _LANGUAGE.match(text):
        raise ValueError("language must be a code such as 'en' or 'en-US'")
    return text


def clean_model(value: str | None) -> str:
    text = (value or "").strip()
    if text and (len(text) > MAX_MODEL or not _MODEL.match(text)):
        raise ValueError("model name is not valid")
    return text


def clean_title(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", "".join(ch for ch in (value or "") if ch.isprintable() or ch in "\t\n")).strip()
    return text[:MAX_TITLE] or None
