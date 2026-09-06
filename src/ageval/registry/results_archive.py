"""Deterministic Attempt result archive (tar + gzip).

Layout inside the archive (paths relative to archive root)::

    .ageval/runs/<run_id>/…

Media type: ``application/vnd.ageval.attempt-result.v1.tar+gzip``
"""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from pathlib import Path
from typing import Any

from ageval.evidence.locators import default_suite_runs_root, run_locator, suite_run_locator
from ageval.evidence.slim import is_vendor_raw_rel
from ageval.registry.media_types import ATTEMPT_RESULT_MEDIA_TYPE, SUITE_RESULT_MEDIA_TYPE

MEDIA_TYPE = ATTEMPT_RESULT_MEDIA_TYPE

# Host sandbox residual under the Attempt run dir — never Hub-facing.
_L1_WORK_ROOT = "l1-work"


def _is_l1_work_rel(rel: str) -> bool:
    """True when *rel* is ``l1-work`` or under it (posix, relative to run_dir)."""
    return rel == _L1_WORK_ROOT or rel.startswith(f"{_L1_WORK_ROOT}/")


def build_attempt_archive(
    run_dir: Path,
    *,
    run_id: str,
    keep_vendor_raw: bool = False,
) -> tuple[bytes, str, int]:
    """Pack ``run_dir`` as ``.ageval/runs/<run_id>/…``; return bytes, blob_digest, size.

    Excludes ``l1-work/**`` even if residual files remain on disk (e.g.
    ``--keep-workspace`` or a failed host cleanup) so Registry blobs stay curated.
    Vendor raw / layer B is skipped unless ``keep_vendor_raw``.
    """
    root = run_dir.expanduser().resolve(strict=True)
    if not root.is_dir():
        msg = f"run directory not found: {root}"
        raise FileNotFoundError(msg)

    prefix = run_locator(run_id)
    members: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_l1_work_rel(rel):
            continue
        if not keep_vendor_raw and is_vendor_raw_rel(rel):
            continue
        members.append((f"{prefix}/{rel}", path))

    return _pack_tree(members)


def extract_attempt_archive(archive: bytes | Path, dest_root: Path) -> Path:
    """Extract into *dest_root*; return path to ``.ageval/runs/<run_id>`` if found."""
    dest = dest_root.expanduser().resolve(strict=False)
    dest.mkdir(parents=True, exist_ok=True)
    closer = None
    fileobj: Any
    if isinstance(archive, Path):
        fileobj = archive.open("rb")
        closer = fileobj
    else:
        fileobj = io.BytesIO(archive)
    try:
        with (
            gzip.GzipFile(fileobj=fileobj, mode="rb") as gz,
            tarfile.open(fileobj=gz, mode="r:") as tar,
        ):
            try:
                tar.extractall(path=dest, filter="data")  # type: ignore[call-arg]
            except TypeError:
                tar.extractall(path=dest)
    finally:
        if closer is not None:
            closer.close()
    from ageval.evidence.locators import default_runs_root

    runs = default_runs_root(dest)
    if runs.is_dir():
        children = [p for p in runs.iterdir() if p.is_dir()]
        if len(children) == 1:
            return children[0]
    return dest


SUITE_MEDIA_TYPE = SUITE_RESULT_MEDIA_TYPE


def _pack_tree(members: list[tuple[str, Path]]) -> tuple[bytes, str, int]:
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        seen_dirs: set[str] = set()
        for arcname, abs_path in members:
            parts = Path(arcname).parts
            for i in range(1, len(parts)):
                d = "/".join(parts[:i])
                if d in seen_dirs:
                    continue
                seen_dirs.add(d)
                info = tarfile.TarInfo(name=d)
                info.type = tarfile.DIRTYPE
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mode = 0o755
                tar.addfile(info)
            data = abs_path.read_bytes()
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(tar_buf.getvalue())
    archive = buf.getvalue()
    digest = f"sha256:{hashlib.sha256(archive).hexdigest()}"
    return archive, digest, len(archive)


def build_suite_archive(suite_dir: Path, *, suite_run_id: str) -> tuple[bytes, str, int]:
    """Pack ``suite_dir`` as ``.ageval/suite-runs/<suite_run_id>/…``.

    Defense in depth: skip any nested ``l1-work/**`` path segments.
    """
    root = suite_dir.expanduser().resolve(strict=True)
    if not root.is_dir():
        msg = f"suite directory not found: {root}"
        raise FileNotFoundError(msg)

    prefix = suite_run_locator(suite_run_id)
    members: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _L1_WORK_ROOT in Path(rel).parts:
            continue
        members.append((f"{prefix}/{rel}", path))

    return _pack_tree(members)


def extract_suite_archive(archive: bytes | Path, dest_root: Path) -> Path:
    """Extract suite bundle; return path to ``.ageval/suite-runs/<id>`` if found."""
    dest = dest_root.expanduser().resolve(strict=False)
    dest.mkdir(parents=True, exist_ok=True)
    closer = None
    fileobj: Any
    if isinstance(archive, Path):
        fileobj = archive.open("rb")
        closer = fileobj
    else:
        fileobj = io.BytesIO(archive)
    try:
        with (
            gzip.GzipFile(fileobj=fileobj, mode="rb") as gz,
            tarfile.open(fileobj=gz, mode="r:") as tar,
        ):
            try:
                tar.extractall(path=dest, filter="data")  # type: ignore[call-arg]
            except TypeError:
                tar.extractall(path=dest)
    finally:
        if closer is not None:
            closer.close()
    suites = default_suite_runs_root(dest)
    if suites.is_dir():
        children = [p for p in suites.iterdir() if p.is_dir()]
        if len(children) == 1:
            return children[0]
    return dest
