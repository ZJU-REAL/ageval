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


def _narrow_summary(summary: dict[str, Any], run_id: str) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    for ref in summary.get("task_refs") or []:
        if not isinstance(ref, dict):
            continue
        if run_id not in _run_ids([ref]):
            continue
        item = dict(ref)
        item["run_id"] = run_id
        item["attempt_run_ids"] = [run_id]
        previous = item.get("previous")
        if isinstance(previous, list):
            item["previous"] = [
                row
                for row in previous
                if isinstance(row, dict) and str(row.get("run_id") or "").strip() == run_id
            ]
        refs.append(item)
    if not refs:
        raise ConfigError(
            "invalid_package",
            f"run {run_id} is not in this suite",
            location="run_id",
        )
    status = str(refs[0].get("status") or "")
    score = refs[0].get("score")
    mean = float(score) if isinstance(score, int | float) and not isinstance(score, bool) else 0.0
    passed = 1.0 if status.upper() == "PASS" else 0.0
    out = dict(summary)
    out["task_refs"] = refs
    out["pass_rate"] = passed
    out["mean_score"] = mean
    metrics = dict(out["metrics"]) if isinstance(out.get("metrics"), dict) else {}
    metrics["pass_rate"] = passed
    metrics["mean_score"] = mean
    out["metrics"] = metrics
    attempts = out.get("attempts")
    if isinstance(attempts, list):
        out["attempts"] = [
            row
            for row in attempts
            if isinstance(row, dict) and str(row.get("run_id") or "").strip() == run_id
        ]
    return out


def _pack_tree(temp: Path, suite_run_id: str) -> tuple[bytes, str, int]:
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


def build_snapshot_share_archive(
    dataset_root: Path, suite_run_id: str, *, run_id: str | None = None
) -> tuple[bytes, str, int]:
    """Return gzip bytes, blob digest, and size for one local suite.

    *run_id* keeps a single Attempt in the snapshot. The local suite is not rewritten.
    """
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
    dataset_identity(summary, location=str(suite_dir / "summary.json"))
    _metrics, task_refs = suite_document.metrics_and_refs(summary)
    wanted = (run_id or "").strip()
    selected = [wanted] if wanted else _run_ids(task_refs)
    if wanted and wanted not in _run_ids(task_refs):
        raise ConfigError(
            "invalid_package",
            f"run {wanted} is not in this suite",
            location="run_id",
        )
    missing: list[str] = []
    run_dirs: list[tuple[str, Path]] = []
    for one_id in selected:
        try:
            run_dirs.append((one_id, resolve_attempt_run_dir(root, one_id)))
        except ConfigError:
            missing.append(one_id)
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
        if wanted:
            summary_path = temp / suite_run_locator(suite_run_id) / "summary.json"
            current = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(current, dict):
                current["task_refs"] = task_refs
            summary_path.write_text(
                json.dumps(_narrow_summary(current, wanted), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        for one_id, run_dir in run_dirs:
            _copy_files(run_dir, temp / run_locator(one_id))
        return _pack_tree(temp, suite_run_id)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _attempt_identity(run_dir: Path) -> tuple[str, str]:
    for name in ("lock.json", "summary.json", "result.json"):
        path = run_dir / name
        doc = _read_json(path)
        if doc is None:
            continue
        try:
            return dataset_identity(doc, location=str(path))
        except ConfigError:
            continue
    raise ConfigError(
        "invalid_schema",
        "missing dataset_id@version",
        location=str(run_dir),
    )


def build_single_attempt_snapshot(dataset_root: Path, run_id: str) -> tuple[bytes, str, int]:
    """Pack one Attempt that is not inside a suite directory."""
    root = dataset_root.expanduser().resolve(strict=False)
    run_dir = resolve_attempt_run_dir(root, run_id)
    dataset_id, dataset_version = _attempt_identity(run_dir)
    result = _read_json(run_dir / "result.json") or {}
    lock = _read_json(run_dir / "lock.json") or {}
    status = str(result.get("status") or "")
    score = result.get("score")
    mean = float(score) if isinstance(score, int | float) and not isinstance(score, bool) else 0.0
    passed = 1.0 if status.upper() == "PASS" else 0.0
    task_id = str(result.get("task_id") or lock.get("task_id") or run_id)
    overlay = lock.get("job_overlay") if isinstance(lock.get("job_overlay"), dict) else None
    summary: dict[str, Any] = {
        "suite_run_id": run_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "status": "finished",
        "exit_code": 0,
        "pass_rate": passed,
        "mean_score": mean,
        "metrics": {"pass_rate": passed, "mean_score": mean},
        "task_refs": [
            {
                "task_id": task_id,
                "status": status,
                "score": score,
                "run_id": run_id,
            }
        ],
    }
    if overlay:
        summary["job_overlay"] = overlay
    with tempfile.TemporaryDirectory(prefix="ageval-snapshot-") as tmp_name:
        temp = Path(tmp_name)
        dest = temp / suite_run_locator(run_id)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _copy_files(run_dir, temp / run_locator(run_id))
        return _pack_tree(temp, run_id)


def snapshot_share_scope(
    dataset_root: Path, suite_run_id: str, run_id: str | None = None
) -> tuple[str, str]:
    """Stored ``(suite_run_id, run_id)``. A single Attempt uses its run id for both."""
    root = dataset_root.expanduser().resolve(strict=False)
    wanted = (run_id or "").strip()
    suite_dir = default_suite_runs_root(root) / suite_run_id
    if suite_dir.is_dir():
        return suite_run_id, wanted
    if wanted and wanted != suite_run_id:
        raise ConfigError(
            "invalid_package",
            "a single job is shared with its own run id",
            location="run_id",
        )
    resolve_attempt_run_dir(root, suite_run_id)
    return suite_run_id, suite_run_id
