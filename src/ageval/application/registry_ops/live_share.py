"""Owner push for a live suite share.

The sidecar ``.ageval/suite-runs/<id>/live-share.json`` binds one token.
Job-terminal and heartbeat pushes patch that token. A missing sidecar
does nothing. A failed push leaves the suite run itself alone.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ageval.application.registry_ops.client import build_registry_client
from ageval.application.registry_ops.snapshot_share import snapshot_member_paths
from ageval.application.suite import document as suite_document
from ageval.config.errors import ConfigError
from ageval.evidence.locators import default_suite_runs_root
from ageval.registry.client import RegistryError
from ageval.registry.results_archive import pack_members
from ageval.registry.share_snapshot import (
    LIVE_SHARE_SIDECAR,
    SNAPSHOT_SHARE_KIND,
    scrub_structure,
    scrub_tree,
)

LIVE_SHARE_HEARTBEAT_S = 45

_push_lock = threading.Lock()


def sidecar_path(dataset_root: Path, suite_run_id: str) -> Path:
    return default_suite_runs_root(dataset_root) / suite_run_id / LIVE_SHARE_SIDECAR


def read_live_share(dataset_root: Path, suite_run_id: str) -> dict[str, Any] | None:
    path = sidecar_path(dataset_root, suite_run_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_live_share(dataset_root: Path, suite_run_id: str, payload: dict[str, Any]) -> None:
    path = sidecar_path(dataset_root, suite_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def push_bound_live_share(
    dataset_root: Path | str,
    suite_run_id: str,
    *,
    include_files: bool,
) -> dict[str, Any]:
    """Patch the bound token from disk. No sidecar means nothing to do."""
    with _push_lock:
        return _push_locked(Path(dataset_root), suite_run_id, include_files=include_files)


def push_suite_share(
    dataset_root: Path | str,
    suite_run_id: str,
    *,
    include_files: bool,
) -> None:
    """Suite boundary. A recorded push failure leaves the suite result alone."""
    push_bound_live_share(dataset_root, suite_run_id, include_files=include_files)


def start_live_share_heartbeat(
    dataset_root: Path,
    suite_run_id: str,
    *,
    interval: float = LIVE_SHARE_HEARTBEAT_S,
) -> Callable[[], None]:
    """Count/status patch while a suite is in progress. Stop with the returned closer."""
    if read_live_share(dataset_root, suite_run_id) is None:
        return lambda: None
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            push_suite_share(dataset_root, suite_run_id, include_files=False)

    thread = threading.Thread(target=loop, name="ageval-live-share", daemon=True)
    thread.start()

    def close() -> None:
        stop.set()
        thread.join(timeout=2)

    return close


def _push_locked(dataset_root: Path, suite_run_id: str, *, include_files: bool) -> dict[str, Any]:
    root = dataset_root.expanduser().resolve(strict=False)
    side = read_live_share(root, suite_run_id)
    if side is None:
        return {"ok": True, "skipped": True}
    if side.get("last_error") == "not_found":
        return {"ok": False, "skipped": True, "error": "not_found"}
    token = str(side.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "invalid_request", "skipped": False}
    try:
        summary = _share_summary(root, suite_run_id)
        client = build_registry_client(
            registry_url=str(side.get("registry_url") or "") or None,
            require_token=True,
            accept_results_url=True,
        )
        raw_sources = side.get("sources")
        sources: dict[str, Any] = raw_sources if isinstance(raw_sources, dict) else {}
        archive: Path | None = None
        new_sources: dict[str, str] = {str(key): str(value) for key, value in sources.items()}
        tmp_dir: tempfile.TemporaryDirectory[str] | None = None
        if include_files:
            changed, new_sources = _changed_members(root, suite_run_id, sources)
            if changed:
                tmp_dir = tempfile.TemporaryDirectory(prefix="ageval-live-patch-")
                archive = _pack_patch(Path(tmp_dir.name), suite_run_id, changed)
        try:
            if archive is None:
                info = client.patch_snapshot_share(
                    token, summary=summary, heartbeat=not include_files
                )
            else:
                info = client.patch_snapshot_share(token, summary=summary, archive=archive)
        finally:
            if tmp_dir is not None:
                tmp_dir.cleanup()
    except RegistryError as exc:
        code = "not_found" if exc.status == 404 or exc.code == "not_found" else exc.code
        side["last_error"] = code
        write_live_share(root, suite_run_id, side)
        return {"ok": False, "error": code, "token": token, "skipped": False}
    except ConfigError as exc:
        side["last_error"] = exc.error_code
        write_live_share(root, suite_run_id, side)
        return {"ok": False, "error": exc.error_code, "token": token, "skipped": False}
    except OSError:
        side["last_error"] = "sync_failed"
        write_live_share(root, suite_run_id, side)
        return {"ok": False, "error": "sync_failed", "token": token, "skipped": False}
    if include_files:
        side["sources"] = new_sources
    side["last_error"] = ""
    write_live_share(root, suite_run_id, side)
    hub = str(side.get("hub_url") or "").rstrip("/")
    url = f"{hub}/s/{token}" if hub else str(info.get("path") or f"/s/{token}")
    return {
        "ok": True,
        "skipped": False,
        "shared": True,
        "kind": SNAPSHOT_SHARE_KIND,
        "mode": "live",
        "token": token,
        "path": info.get("path") or f"/s/{token}",
        "url": url,
        "suite_run_id": suite_run_id,
        "run_id": "",
        "dataset_id": summary.get("dataset_id") or "",
    }


def _share_summary(dataset_root: Path, suite_run_id: str) -> dict[str, Any]:
    suite_dir = default_suite_runs_root(dataset_root) / suite_run_id
    summary = suite_document.load_summary_file(
        suite_dir / "summary.json",
        missing_code="invalid_package",
        invalid_code="invalid_package",
    )
    progress_path = suite_dir / "progress.json"
    if progress_path.is_file():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            progress = None
        if isinstance(progress, dict):
            running = progress.get("running")
            summary = dict(summary)
            summary["progress"] = {
                "done": progress.get("done"),
                "total": progress.get("total"),
                "status": progress.get("status"),
                "running": len(running) if isinstance(running, list) else 0,
            }
    cleaned = scrub_structure(summary)
    return cleaned if isinstance(cleaned, dict) else {}


def source_hashes(dataset_root: Path, suite_run_id: str) -> dict[str, str]:
    _changed, current = _changed_members(dataset_root, suite_run_id, {})
    return current


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _changed_members(
    dataset_root: Path,
    suite_run_id: str,
    sources: dict[str, Any],
) -> tuple[list[tuple[str, Path]], dict[str, str]]:
    changed: list[tuple[str, Path]] = []
    current: dict[str, str] = {}
    for rel, src in snapshot_member_paths(dataset_root, suite_run_id, allow_missing_runs=True):
        digest = _file_sha(src)
        current[rel] = digest
        if sources.get(rel) != digest:
            changed.append((rel, src))
    return changed, current


def _pack_patch(temp: Path, suite_run_id: str, members: list[tuple[str, Path]]) -> Path:
    for rel, src in members:
        dest = temp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    scrub_tree(temp)
    marker = {
        "kind": SNAPSHOT_SHARE_KIND,
        "version": 1,
        "suite_run_id": suite_run_id,
    }
    (temp / "snapshot-share.json").write_text(
        json.dumps(marker, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    packed = [
        (path.relative_to(temp).as_posix(), path)
        for path in sorted(temp.rglob("*"))
        if path.is_file()
    ]
    raw, _digest, _size = pack_members(packed)
    archive = temp / "patch.tar.gz"
    archive.write_bytes(raw)
    return archive
