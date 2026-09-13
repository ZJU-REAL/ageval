"""Verifier checks.json and dataset script preview (observational, not PASS)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.evidence.checks import CHECKS_REL, package_script_rel
from ageval.evidence.locators import safe_id_segment
from ageval.viewer.jobs import get_job
from ageval.viewer.trials.constants import MAX_FILE_BYTES, TEXT_SUFFIXES
from ageval.viewer.trials.paths import _safe_run_id, resolve_evidence_root, safe_under


def trial_evaluation_checks(
    dataset_root: Path,
    job_id: str,
    task_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Rows from ``evaluation/checks.json``. Missing file → empty list."""
    root = dataset_root.expanduser().resolve(strict=False)
    safe_id_segment(job_id, field="job_id")
    task_id = safe_id_segment(task_id, field="task_id")
    rid = _safe_run_id(run_id)
    get_job(root, job_id)
    evidence = resolve_evidence_root(root, rid, task_id=task_id, require_task_match=True)
    path = evidence / CHECKS_REL
    if not path.is_file():
        return {
            "ok": True,
            "run_id": rid,
            "task_id": task_id,
            "schema": None,
            "checks": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "ok": True,
            "run_id": rid,
            "task_id": task_id,
            "schema": None,
            "checks": [],
            "note": "checks.json is not valid JSON",
        }
    if not isinstance(data, dict):
        return {
            "ok": True,
            "run_id": rid,
            "task_id": task_id,
            "schema": None,
            "checks": [],
            "note": "checks.json is not an object",
        }
    raw = data.get("checks")
    checks = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    schema = data.get("schema")
    return {
        "ok": True,
        "run_id": rid,
        "task_id": task_id,
        "schema": schema if isinstance(schema, str) else None,
        "checks": checks,
    }


def trial_package_file(
    dataset_root: Path,
    job_id: str,
    task_id: str,
    run_id: str,
    *,
    relpath: str,
) -> dict[str, Any]:
    """Read a dataset file for Verifier 'View script'. Not an evidence copy."""
    root = dataset_root.expanduser().resolve(strict=False)
    safe_id_segment(job_id, field="job_id")
    task_id = safe_id_segment(task_id, field="task_id")
    rid = _safe_run_id(run_id)
    get_job(root, job_id)
    resolve_evidence_root(root, rid, task_id=task_id, require_task_match=True)
    resolved = package_script_rel(relpath, task_id)
    if resolved is None:
        raise ConfigError(
            "invalid_package",
            "script path rejected",
            location=relpath or ".",
        )
    if ".ageval" in Path(resolved).parts:
        raise ConfigError(
            "invalid_package",
            "script path rejected",
            location=resolved,
        )
    path = safe_under(root, resolved)
    if not path.is_file():
        raise ConfigError(
            "unknown_task",
            f"file not found: {resolved}",
            location=resolved,
        )
    size = path.stat().st_size
    suffix = path.suffix.lower()
    if path.name in {".env", ".env.local", ".env.production"} or path.name.startswith(".env."):
        return {
            "ok": True,
            "run_id": rid,
            "path": resolved,
            "name": path.name,
            "size": size,
            "encoding": "redacted",
            "truncated": False,
            "content": None,
            "note": "secret-like filename; content not shown",
        }
    is_text = suffix in TEXT_SUFFIXES or suffix in {".py"}
    if not is_text:
        return {
            "ok": True,
            "run_id": rid,
            "path": resolved,
            "name": path.name,
            "size": size,
            "encoding": "binary",
            "truncated": False,
            "content": None,
            "note": "binary file; preview not shown",
        }
    if size > MAX_FILE_BYTES:
        raw = path.read_bytes()[:MAX_FILE_BYTES]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "run_id": rid,
            "path": resolved,
            "name": path.name,
            "size": size,
            "encoding": "utf-8",
            "truncated": True,
            "content": text,
            "note": f"truncated to first {MAX_FILE_BYTES} bytes",
        }
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "run_id": rid,
        "path": resolved,
        "name": path.name,
        "size": size,
        "encoding": "utf-8",
        "truncated": False,
        "content": text,
    }
