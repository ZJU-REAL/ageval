"""Read sealed Attempt files for analyzers. Never writes them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.application.analysis.errors import ANALYSIS_INPUT
from ageval.config.errors import ConfigError
from ageval.evidence.attempt_record import read_attempt_result
from ageval.evidence.trajectory import TRAJECTORY_FILENAME

_STATUSES = frozenset({"PASS", "FAIL", "ERROR"})


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_trajectory(run_dir: Path) -> list[dict[str, Any]]:
    """Parse ``trajectory.jsonl``. Missing or empty is an input error."""
    path = run_dir / TRAJECTORY_FILENAME
    if not path.is_file():
        raise ConfigError(
            ANALYSIS_INPUT,
            f"trajectory.jsonl is missing for {run_dir.name}",
            location=str(path),
        )
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            ANALYSIS_INPUT,
            f"cannot read trajectory.jsonl: {exc}",
            location=str(path),
        ) from exc
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    if not rows:
        raise ConfigError(
            ANALYSIS_INPUT,
            f"trajectory.jsonl has no rows for {run_dir.name}",
            location=str(path),
        )
    return rows


def attempt_status(run_dir: Path, *, fallback: str | None = None) -> str | None:
    """PASS / FAIL / ERROR from ``result.json``, else ``summary.json``, else *fallback*."""
    result = read_attempt_result(run_dir)
    status = _status_of(result)
    if status:
        return status
    summary = read_json_object(run_dir / "summary.json")
    status = _status_of(summary)
    if status:
        return status
    if isinstance(summary, dict):
        nested = summary.get("result")
        status = _status_of(nested if isinstance(nested, dict) else None)
        if status:
            return status
    if isinstance(fallback, str) and fallback.strip():
        text = fallback.strip().upper()
        if text in _STATUSES:
            return text
    return None


def _status_of(doc: dict[str, Any] | None) -> str | None:
    if not isinstance(doc, dict):
        return None
    raw = doc.get("status")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().upper()
    if text in _STATUSES:
        return text
    return None
