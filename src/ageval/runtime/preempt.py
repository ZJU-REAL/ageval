"""Suite preempt request and the Attempt handshake that honors it.

``preempt.requested`` is not ``cancel.requested``. Drain cancel lets in-flight
units finish. Preempt stops new claims, lets the current model turn finish,
and leaves that Attempt unsealed so ``--resume-suite`` attaches the same one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PREEMPT_SCHEMA = "ageval.suite.preempt/1"
PREEMPT_FILENAME = "preempt.requested"


class AttemptSuspended(BaseException):
    """The run phase stopped for preempt. Not a phase failure and not a verdict."""


@dataclass(frozen=True)
class PreemptRequest:
    """One suite preempt document. ``tasks is None`` means the whole suite."""

    suite_run_id: str
    tasks: frozenset[str] | None


def preempt_request_path(dataset_root: Path, suite_run_id: str) -> Path:
    from ageval.evidence.locators import default_suite_runs_root

    root = dataset_root.expanduser().resolve(strict=False)
    return default_suite_runs_root(root) / suite_run_id / PREEMPT_FILENAME


def request_suite_preempt(
    dataset_root: Path,
    suite_run_id: str,
    *,
    tasks: list[str] | None = None,
) -> Path:
    """Write ``preempt.requested``. Does not signal the controller process."""
    path = preempt_request_path(dataset_root, suite_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    named = _task_ids(tasks)
    payload: dict[str, Any] = {
        "schema": PREEMPT_SCHEMA,
        "suite_run_id": suite_run_id,
        "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if named:
        payload["tasks"] = named
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def clear_suite_preempt(dataset_root: Path, suite_run_id: str) -> bool:
    """Remove ``preempt.requested`` so resume can schedule again."""
    path = preempt_request_path(dataset_root, suite_run_id)
    if not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


def is_suite_preempt_requested(dataset_root: Path, suite_run_id: str) -> bool:
    return preempt_request_path(dataset_root, suite_run_id).is_file()


def read_suite_preempt(dataset_root: Path, suite_run_id: str) -> PreemptRequest | None:
    """The request on disk. A present but unreadable file still stops the suite."""
    path = preempt_request_path(dataset_root, suite_run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return PreemptRequest(suite_run_id=suite_run_id, tasks=None)
    if not isinstance(data, dict):
        return PreemptRequest(suite_run_id=suite_run_id, tasks=None)
    named = _task_ids(data.get("tasks"))
    return PreemptRequest(
        suite_run_id=str(data.get("suite_run_id") or suite_run_id),
        tasks=frozenset(named) if named else None,
    )


def preempt_blocks_task(dataset_root: Path, suite_run_id: str, task_id: str) -> bool:
    """True when this task must not start, or an in-flight unit must suspend."""
    request = read_suite_preempt(dataset_root, suite_run_id)
    if request is None:
        return False
    if request.tasks is None:
        return True
    return task_id in request.tasks


def preempt_stops_suite(dataset_root: Path, suite_run_id: str) -> bool:
    """True when no further unit of any task may be claimed."""
    request = read_suite_preempt(dataset_root, suite_run_id)
    return request is not None and request.tasks is None


def _task_ids(raw: object) -> list[str]:
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def mark_attempt_preempted(ctx: Any) -> None:
    """Close a cut-off turn, checkpoint, and remember that the box stays up.

    A completed model turn stays in the log. An open streamed turn is aborted
    so resume sends it again. No ``result.json`` is written here.
    """
    ctx.suspended = True
    log = getattr(ctx, "activity", None)
    if log is not None:
        # Abort a cut-off model turn. Leave the invoke in-flight so resume
        # sends that turn again instead of replaying an empty success.
        _reconcile_open_steps(ctx, log)
        if not log.has_completed_phase("preempted"):
            elapsed = ctx.active_elapsed_ms() if hasattr(ctx, "active_elapsed_ms") else 0.0
            limit = ctx.limit_name() if hasattr(ctx, "limit_name") else None
            log.append(
                request_id="phase_preempted",
                kind="phase",
                status="completed",
                payload={
                    "phase": "preempted",
                    "elapsed_ms": elapsed,
                    "limit_reached": limit,
                    "checkpoint_seq": None,
                },
                prepare=_checkpoint_prepare(ctx),
            )
    record = getattr(ctx, "record_fact", None)
    if callable(record):
        record("attempt_preempted", {"kept_environment": True})


def _checkpoint_prepare(ctx: Any):
    from ageval.attempt.recover import capture_box

    def prepare(seq: int) -> dict[str, int | None]:
        return {"checkpoint_seq": capture_box(ctx, seq)}

    return prepare


def _reconcile_open_steps(ctx: Any, log: Any) -> None:
    from ageval.evidence.activity import ActivityScope, reconcile_inflight_tail

    seen: set[tuple[str, str]] = set()
    for record in list(log.records):
        if record.kind not in {"model_turn", "tool_call"} or record.status != "in_flight":
            continue
        session_id = str(record.payload.get("session_id") or "")
        invoke_id = str(record.payload.get("invoke_request_id") or "")
        if not session_id or (session_id, invoke_id) in seen:
            continue
        seen.add((session_id, invoke_id))
        scope = ActivityScope(log, session_id=session_id, invoke_request_id=invoke_id)
        reconcile_inflight_tail(scope, prepare=_checkpoint_prepare(ctx))
