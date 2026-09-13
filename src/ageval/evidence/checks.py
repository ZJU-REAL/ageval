"""Persist optional evaluator ``checks`` as ``evaluation/checks.json``.

Observational — never PASS. Layout strings live here. Core does not invent
this list from ``evaluate_exec`` facts or from ``evaluator.py``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

CHECKS_SCHEMA = "ageval.evaluation.checks/1"
CHECKS_REL = "evaluation/checks.json"
_STREAM_LIMIT = 65_536
_TRUNCATION_MARK = "\n…[truncated]"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _clip_stream(value: Any) -> str | None:
    text = _as_text(value)
    if text is None:
        return None
    if len(text) <= _STREAM_LIMIT:
        return text
    keep = max(0, _STREAM_LIMIT - len(_TRUNCATION_MARK))
    return text[:keep] + _TRUNCATION_MARK


def _as_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _as_exit_code(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def normalize_check_row(raw: Any) -> dict[str, Any] | None:
    """Keep known observational fields. Rows without ``id`` are dropped."""
    if not isinstance(raw, Mapping):
        return None
    check_id = raw.get("id")
    if not isinstance(check_id, str) or not check_id.strip():
        return None
    row: dict[str, Any] = {"id": check_id.strip()}
    title = raw.get("title")
    if isinstance(title, str) and title.strip():
        row["title"] = title.strip()
    status = raw.get("status")
    if isinstance(status, str) and status.strip():
        row["status"] = status.strip()
    score = _as_score(raw.get("score"))
    if score is not None:
        row["score"] = score
    script = raw.get("script")
    if isinstance(script, str) and script.strip():
        row["script"] = script.strip()
    environment = raw.get("environment")
    if isinstance(environment, str) and environment.strip():
        row["environment"] = environment.strip()
    exit_code = _as_exit_code(raw.get("exit_code"))
    if exit_code is not None:
        row["exit_code"] = exit_code
    stdout = _clip_stream(raw.get("stdout"))
    if stdout is not None:
        row["stdout"] = stdout
    stderr = _clip_stream(raw.get("stderr"))
    if stderr is not None:
        row["stderr"] = stderr
    return row


def checks_document(raw_checks: Any) -> dict[str, Any] | None:
    """Wrap a well-formed ``checks`` list. Absent / empty / malformed → None."""
    if not isinstance(raw_checks, list):
        return None
    rows = [row for item in raw_checks if (row := normalize_check_row(item)) is not None]
    if not rows:
        return None
    return {"schema": CHECKS_SCHEMA, "checks": rows}


def package_script_rel(script: str, task_id: str) -> str | None:
    """Resolve a check ``script`` to a dataset-relative path. Reject traversal."""
    if not isinstance(script, str) or not script.strip():
        return None
    clean = script.strip().replace("\\", "/")
    if clean.startswith("/") or clean.startswith("~"):
        return None
    segments = clean.split("/")
    if any(part in {"", ".", "..", ".ageval"} for part in segments):
        return None
    if clean.startswith("tasks/"):
        return clean
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    return f"tasks/{task_id.strip()}/{clean}"


def persist_evaluation_checks(store: Any, verdict: Mapping[str, Any] | None) -> None:
    """Write ``evaluation/checks.json`` when the verdict carries well-formed checks.

    Missing or malformed ``checks`` is a no-op. Does not read phase facts.
    """
    if not isinstance(verdict, Mapping):
        return
    doc = checks_document(verdict.get("checks"))
    if doc is None:
        return
    store.write_evaluation("checks", doc)
