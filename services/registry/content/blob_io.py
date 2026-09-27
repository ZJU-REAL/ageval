"""File-oriented blob helpers. Production put/open paths take a Path or fileobj."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, BinaryIO


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def copy_fileobj(src: BinaryIO, dest: Path, *, chunk: int = 1024 * 1024) -> int:
    written = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while True:
            block = src.read(chunk)
            if not block:
                break
            out.write(block)
            written += len(block)
    return written


def read_blob(blobs: Any, blob_digest: str, *, prefix: str) -> bytes | None:
    """Load one object for preview / list_files (not the whole-object HTTP path)."""
    fh = blobs.open(blob_digest, prefix=prefix)
    if fh is None:
        return None
    with fh:
        return fh.read()
