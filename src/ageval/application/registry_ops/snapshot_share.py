"""Build a snapshot-share archive from a local suite run.

Copies into a temp tree, scrubs secrets there, and packs the blob.
The local suite and attempt directories are not modified.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ageval.application.suite import document as suite_document
from ageval.config.errors import ConfigError
from ageval.evidence.identity import dataset_identity
from ageval.evidence.locators import (
    default_runs_root,
    default_suite_runs_root,
    resolve_attempt_run_dir,
    run_locator,
    suite_run_locator,
)
from ageval.evidence.slim import is_vendor_raw_rel
from ageval.registry.results_archive import pack_members
from ageval.registry.share_snapshot import SNAPSHOT_SHARE_KIND, scrub_tree


def _skip_rel(rel: str) -> bool:
    return "l1-work" in Path(rel).parts or is_vendor_raw_rel(rel)


def _copy_files(src: Path, dest: Path) -> None:
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        if _skip_rel(rel):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def _run_ids(task_refs: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: object) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    for ref in task_refs:
        ids = ref.get("attempt_run_ids")
        if isinstance(ids, list) and ids:
            for run_id in ids:
                add(run_id)
        else:
            add(ref.get("run_id"))
        previous = ref.get("previous")
        if isinstance(previous, list):
            for item in previous:
                if isinstance(item, dict):
                    add(item.get("run_id"))
    return out


def build_snapshot_share_archive(dataset_root: Path, suite_run_id: str) -> tuple[bytes, str, int]:
    """Return gzip bytes, blob digest, and size for one local suite."""
    root = dataset_root.expanduser().resolve(strict=False)
    suite_dir = default_suite_runs_root(root) / suite_run_id
    if not suite_dir.is_dir():
        raise ConfigError(
            "invalid_package",
            f"suite directory not found: {suite_dir}",
            location=str(suite_dir),
        )
    summary = suite_document.load_summary_file(
        suite_dir / "summary.json",
        missing_code="invalid_package",
        invalid_code="invalid_package",
    )
    suite_document.refuse_in_progress_snapshot(
        summary, suite_dir=suite_dir, suite_run_id=suite_run_id
    )
    dataset_identity(summary, location=str(suite_dir / "summary.json"))
    _metrics, task_refs = suite_document.metrics_and_refs(summary)
    missing: list[str] = []
    run_dirs: list[tuple[str, Path]] = []
    for run_id in _run_ids(task_refs):
        try:
            run_dirs.append((run_id, resolve_attempt_run_dir(root, run_id)))
        except ConfigError:
            missing.append(run_id)
    if missing:
        preview = ", ".join(missing[:8])
        raise ConfigError(
            "invalid_package",
            f"missing local run dir(s) under .ageval/runs/ for: {preview}",
            location=str(default_runs_root(root)),
        )

    with tempfile.TemporaryDirectory(prefix="ageval-snapshot-") as tmp_name:
        temp = Path(tmp_name)
        _copy_files(suite_dir, temp / suite_run_locator(suite_run_id))
        for run_id, run_dir in run_dirs:
            _copy_files(run_dir, temp / run_locator(run_id))
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
        members = [
            (path.relative_to(temp).as_posix(), path)
            for path in sorted(temp.rglob("*"))
            if path.is_file()
        ]
        return pack_members(members)
