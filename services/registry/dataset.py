"""Dataset draft slot, task-set fingerprint, and suite completeness.

Authority: docs/design/08-hub-registry-and-agents.md.
Complete ≠ suite PASS. FAIL/ERROR still count as a result.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

DRAFT_VERSION = "draft"
DRAFT_SLOT = "draft"

BOUND_RELEASE = "release"
BOUND_DRAFT = "draft"
BOUND_SOURCE = "source"
BOUND_UNKNOWN = "unknown"
# Bound kinds that may rank on a public board once approved.
RANKED_BOUND_KINDS = frozenset({BOUND_RELEASE, BOUND_SOURCE})


def is_draft_version(version: str | None) -> bool:
    return str(version or "").strip().casefold() == DRAFT_VERSION


def task_ids_from_file_paths(paths: Iterable[str]) -> frozenset[str]:
    """Member task ids from package archive paths (`tasks/<id>/…`)."""
    ids: set[str] = set()
    for raw in paths:
        text = str(raw or "").strip().lstrip("/")
        if not text or text.startswith(".."):
            continue
        parts = text.split("/")
        if len(parts) >= 2 and parts[0] == "tasks" and parts[1]:
            ids.add(parts[1])
    return frozenset(ids)


def task_set_digest(task_ids: Iterable[str]) -> str:
    ordered = sorted({str(t).strip() for t in task_ids if str(t).strip()})
    payload = "\n".join(ordered).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def task_has_result(ref: Mapping[str, Any]) -> bool:
    """True when the task was evaluated (PASS/FAIL/ERROR all count)."""
    tid = str(ref.get("task_id") or "").strip()
    if not tid:
        return False
    status = str(ref.get("status") or "").strip()
    if status:
        return True
    return ref.get("score") is not None


def result_task_ids(task_refs: Iterable[Any]) -> frozenset[str]:
    have: set[str] = set()
    for ref in task_refs:
        if not isinstance(ref, Mapping):
            continue
        if not task_has_result(ref):
            continue
        have.add(str(ref.get("task_id") or "").strip())
    have.discard("")
    return frozenset(have)


def suite_is_complete(
    *,
    bound_task_ids: Iterable[str],
    task_refs: Iterable[Any],
) -> bool:
    """Every bound-version task has a result. Empty bound set is incomplete."""
    required = frozenset(str(t).strip() for t in bound_task_ids if str(t).strip())
    if not required:
        return False
    return required <= result_task_ids(task_refs)


def parse_task_refs(tasks_json: str | list[Any] | None) -> list[dict[str, Any]]:
    if isinstance(tasks_json, list):
        return [r for r in tasks_json if isinstance(r, dict)]
    if not tasks_json:
        return []
    try:
        data = json.loads(tasks_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]
