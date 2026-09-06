"""Single reader for a suite ``summary.json``.

Execute/resume writes the summary (``suite_run``); Hub upload and the
Viewer/CLI job listing read it. This module is the one place that parses and
validates the file, so metrics backfill and path layout have one home. Callers
keep their public ``ConfigError`` codes by passing them to
``load_summary_file``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ageval.application.suite.suite_metrics import (
    ensure_suite_metrics,
    ensure_suite_task_refs,
    task_refs_for_summary,
)
from ageval.config.errors import ConfigError
from ageval.evidence.locators import default_suite_runs_root

_ZERO_METRICS: dict[str, Any] = {
    "pass_rate": 0.0,
    "mean_score": 0.0,
    "n_tasks": 0,
    "n_pass": 0,
    "n_fail": 0,
    "n_error": 0,
    "missing_score_as": 0.0,
}


def suite_dir(dataset_root: Path | str, suite_run_id: str) -> Path:
    """``<dataset>/.ageval/suite-runs/<id>``."""
    return default_suite_runs_root(dataset_root) / suite_run_id


def summary_path(dataset_root: Path | str, suite_run_id: str) -> Path:
    """``<dataset>/.ageval/suite-runs/<id>/summary.json``."""
    return suite_dir(dataset_root, suite_run_id) / "summary.json"


def load_summary_file(path: Path, *, missing_code: str, invalid_code: str) -> dict[str, Any]:
    """Parse one ``summary.json``; the caller picks its public error codes."""
    if not path.is_file():
        raise ConfigError(
            missing_code,
            f"suite summary not found: {path}",
            location=str(path),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(
            invalid_code,
            f"cannot read suite summary: {exc}",
            location=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            invalid_code,
            "suite summary must be a JSON object",
            location=str(path),
        )
    return data


def load_suite_summary(dataset_root: Path | str, suite_run_id: str) -> dict[str, Any]:
    """Execute/resume contract: missing → ``suite_not_found``, bad → ``suite_summary_invalid``."""
    return load_summary_file(
        summary_path(dataset_root, suite_run_id),
        missing_code="suite_not_found",
        invalid_code="suite_summary_invalid",
    )


def task_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Valid ``tasks[]`` entries (dicts only)."""
    raw = summary.get("tasks")
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict)]


def attempt_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Valid ``attempts[]`` entries (dicts only)."""
    raw = summary.get("attempts")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict)]


def metrics_and_refs(summary: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Metrics + task_refs with one backfill policy.

    ``ensure_suite_metrics`` / ``ensure_suite_task_refs`` are the authority:
    missing pass@k maps are recomputed when recoverable. The Viewer's
    zero-metrics fallback applies only when nothing can be derived at all.
    """
    rows = task_rows(summary)
    metrics = ensure_suite_metrics(summary, task_rows=rows)
    raw_refs = summary.get("task_refs")
    existing: list[dict[str, Any]] | None = None
    if isinstance(raw_refs, list):
        existing = [t for t in raw_refs if isinstance(t, dict)]
    refs = ensure_suite_task_refs(summary, task_rows=rows, existing_refs=existing)
    if not refs:
        refs = task_refs_for_summary(rows)
    if not metrics:
        metrics = dict(_ZERO_METRICS)
    return metrics, refs


def refuse_in_progress_snapshot(
    summary: Mapping[str, Any], *, suite_dir: Path, suite_run_id: str
) -> None:
    """Upload contract: a live running/cancelling snapshot is not a complete suite."""
    snapshot_status = str(summary.get("status") or "").strip().lower()
    if snapshot_status in {"running", "cancelling"}:
        raise ConfigError(
            "suite_in_progress",
            f"suite {suite_run_id} is still {snapshot_status}; "
            "an in-progress summary is an observational snapshot, not a complete suite",
            location=str(Path(suite_dir) / "summary.json"),
        )
