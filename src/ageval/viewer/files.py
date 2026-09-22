"""Read-only package file tree and size-capped preview.

Paths stay under one allowed root. ``..``, a ``credentials`` path segment, and
symlink escapes are refused. Secret-like basenames are redacted the same way as
Attempt evidence preview.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.viewer.trials.constants import (
    MAX_FILE_BYTES,
    MAX_TREE_ENTRIES,
    is_preview_text,
    is_secret_basename,
)
from ageval.viewer.trials.paths import safe_under

_JOB_DIR_NAMES = frozenset({"runs", "suite-runs"})


def list_tree(root: Path, *, omit_job_dirs: bool) -> dict[str, Any]:
    """Flat file entries under *root*. Dataset job trees are omitted when asked."""
    base = root.resolve(strict=False)
    entries: list[dict[str, Any]] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(dirpath)
        try:
            rel_dir = current.resolve(strict=False).relative_to(base)
        except ValueError:
            dirnames[:] = []
            continue
        dirnames[:] = _kept_dirs(
            current,
            dirnames,
            rel_dir=rel_dir,
            base=base,
            omit_job_dirs=omit_job_dirs,
        )
        for name in sorted(filenames):
            if len(entries) >= MAX_TREE_ENTRIES:
                truncated = True
                break
            if name == "credentials":
                continue
            path = current / name
            try:
                resolved = path.resolve(strict=False)
                resolved.relative_to(base)
            except (OSError, ValueError):
                continue
            if not path.is_file():
                continue
            rel = _rel(base, path)
            if rel is None or _blocked_package_path(rel, omit_job_dirs=omit_job_dirs):
                continue
            if Path(rel).name == "credentials":
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entries.append({"path": rel, "name": path.name, "type": "file", "size": size})
        if truncated:
            break
    return {"ok": True, "entries": entries, "truncated": truncated}


def read_preview(root: Path, relative: str, *, omit_job_dirs: bool) -> dict[str, Any]:
    """Preview one file under *root*, or refuse."""
    _reject_credentials(relative)
    if _blocked_package_path(relative, omit_job_dirs=omit_job_dirs):
        raise ConfigError(
            "invalid_package",
            "path is not on the package tree",
            location=relative,
        )
    path = safe_under(root, relative)
    _reject_credentials(
        path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    )
    if not path.is_file():
        raise ConfigError(
            "unknown_file",
            f"file not found: {relative}",
            location=relative,
        )
    size = path.stat().st_size
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    if is_secret_basename(path.name):
        return {
            "ok": True,
            "path": relative,
            "name": path.name,
            "size": size,
            "media_type": mime,
            "encoding": "redacted",
            "truncated": False,
            "content": None,
            "note": "secret-like filename; content not shown",
        }
    is_text = is_preview_text(path.name, path.suffix.lower(), mime)
    if not is_text:
        return {
            "ok": True,
            "path": relative,
            "name": path.name,
            "size": size,
            "media_type": mime,
            "encoding": "binary",
            "truncated": False,
            "content": None,
            "note": "binary file; preview not shown",
        }
    truncated = size > MAX_FILE_BYTES
    raw = path.read_bytes()[:MAX_FILE_BYTES] if truncated else path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    payload: dict[str, Any] = {
        "ok": True,
        "path": relative,
        "name": path.name,
        "size": size,
        "media_type": mime,
        "encoding": "utf-8",
        "truncated": truncated,
        "content": text,
    }
    if truncated:
        payload["note"] = f"truncated to first {MAX_FILE_BYTES} bytes"
    return payload


def contained(parent: Path, child: Path) -> bool:
    """True when *child* resolves inside *parent*."""
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _kept_dirs(
    current: Path,
    names: list[str],
    *,
    rel_dir: Path,
    base: Path,
    omit_job_dirs: bool,
) -> list[str]:
    kept: list[str] = []
    for name in sorted(names):
        if name in {"__pycache__", ".git"} or name == "credentials":
            continue
        if omit_job_dirs and rel_dir.parts == (".ageval",) and name in _JOB_DIR_NAMES:
            continue
        child = current / name
        try:
            child.resolve(strict=False).relative_to(base)
        except (OSError, ValueError):
            continue
        kept.append(name)
    return kept


def _rel(base: Path, path: Path) -> str | None:
    try:
        rel = path.resolve(strict=False).relative_to(base)
    except ValueError:
        return None
    text = rel.as_posix()
    return text or None


def _blocked_package_path(relative: str, *, omit_job_dirs: bool) -> bool:
    if not omit_job_dirs:
        return False
    parts = Path(relative).parts
    return len(parts) >= 2 and parts[0] == ".ageval" and parts[1] in _JOB_DIR_NAMES


def _reject_credentials(relative: str) -> None:
    if "credentials" in Path(relative).parts:
        raise ConfigError(
            "invalid_package",
            "credentials are not served",
            location=relative,
        )
