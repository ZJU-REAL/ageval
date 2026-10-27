"""Prepare a terminal-action replay before any environment starts.

The child Attempt is new. The source directory and its environment are not
attached or rewritten. A non-replayable manifest refuses here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.evidence.locators import default_runs_root
from ageval.evidence.replay_input import (
    REPLAY_REPORT_FORMAT,
    diagnose_replay,
    identities_from_lock,
)
from ageval.plugins.base import BaseExecutor
from ageval.plugins.slots import EXECUTOR


class ReplayRejection(ConfigError):
    """A replay that must stop before an environment starts."""


@dataclass(frozen=True)
class ReplayRequest:
    source_attempt_id: str
    evaluate: bool = False


def source_attempt_dir(dataset: Path, attempt_id: str) -> Path:
    name = attempt_id.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ReplayRejection(
            "unknown_run",
            "attempt id must be a single directory name",
            location="--run",
        )
    root = default_runs_root(dataset) / name
    if not root.is_dir():
        raise ReplayRejection(
            "unknown_run",
            "attempt directory was not found",
            location="--run",
        )
    return root


def source_task_id(dataset: Path, attempt_id: str) -> str:
    source = source_attempt_dir(dataset, attempt_id)
    lock = _read_lock(source)
    task_id = lock.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ReplayRejection(
            "replay_source_invalid",
            "source lock has no task_id",
            location="--run",
        )
    return task_id.strip()


def source_profiles_file(dataset: Path, attempt_id: str) -> Path:
    """Write the source job overlay so the child lock keeps the same harness."""
    source = source_attempt_dir(dataset, attempt_id)
    lock = _read_lock(source)
    overlay = lock.get("job_overlay")
    if not isinstance(overlay, dict):
        raise ReplayRejection(
            "replay_source_invalid",
            "source lock has no job_overlay",
            location="--run",
        )
    from ageval.config.profiles import job_overlay_to_profiles_document

    document = job_overlay_to_profiles_document(overlay)
    import tempfile

    import yaml

    fd, name = tempfile.mkstemp(prefix="ageval-replay-profiles-", suffix=".yaml")
    path = Path(name)
    import os

    os.close(fd)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def load_replay_plan(
    dataset: Path,
    request: ReplayRequest,
    *,
    lock_summary: Mapping[str, object],
    registry: Any,
    executor_id: str,
) -> Mapping[str, object]:
    """Diagnose the retained program. Does not start a box."""
    source = source_attempt_dir(dataset, request.source_attempt_id)
    registration = registry.get_registration(EXECUTOR, executor_id)
    impl = getattr(registration, "impl", None) if registration is not None else None
    classify = (
        getattr(impl, "classify_replay_actions", None) or BaseExecutor.classify_replay_actions
    )
    diagnosis = diagnose_replay(source, identities_from_lock(lock_summary), classify)
    if not diagnosis.replayable:
        raise ReplayRejection(
            diagnosis.error or "replay_not_replayable",
            diagnosis.message or "replay input is not executable",
            location="--run",
        )
    return diagnosis.manifest


async def run_replay(
    dataset: Path | str,
    source_attempt_id: str,
    *,
    evaluate: bool = False,
    keep_recovery_state: bool = False,
    keep_workspace: bool = False,
) -> tuple[int, dict[str, object]]:
    """Lock the source harness, refuse if the program is not executable, then run it."""
    from ageval.application.run import run_attempt

    root = Path(dataset)
    try:
        task_id = source_task_id(root, source_attempt_id)
        profiles = source_profiles_file(root, source_attempt_id)
    except ReplayRejection as exc:
        return 2, _refused_report(source_attempt_id, exc)
    try:
        _code, result = await run_attempt(
            root,
            task_id,
            profiles_path=profiles,
            replay=ReplayRequest(source_attempt_id, evaluate=evaluate),
            keep_recovery_state=keep_recovery_state,
            keep_workspace=keep_workspace,
        )
    finally:
        profiles.unlink(missing_ok=True)
    report = report_from_result(source_attempt_id, result)
    return replay_exit_code(report), report


def _refused_report(source_attempt_id: str, exc: ReplayRejection) -> dict[str, object]:
    return {
        "format": REPLAY_REPORT_FORMAT,
        "source_attempt_id": source_attempt_id,
        "attempt_id": "",
        "status": "error",
        "first_divergence": None,
        "evidence_path": "",
        "evaluator_status": None,
        "reproduced_failure": False,
        "error": {"title": exc.error_code, "message": exc.message},
    }


def report_from_result(source_attempt_id: str, result: Any) -> dict[str, object]:
    """Machine-readable replay outcome. Evaluator status stays a separate field."""
    replay = getattr(result, "replay", None)
    document = replay if isinstance(replay, dict) else {}
    error = getattr(result, "error", None)
    evaluated = document.get("evaluated") is True
    status = document.get("status") if isinstance(document.get("status"), str) else "error"
    evidence = str(getattr(result, "evidence_path", "") or "")
    payload: dict[str, object] = {
        "format": REPLAY_REPORT_FORMAT,
        "source_attempt_id": source_attempt_id,
        "attempt_id": Path(evidence).name if evidence else "",
        "status": status,
        "first_divergence": document.get("first_divergence"),
        "evidence_path": evidence,
        "evaluator_status": getattr(result, "status", None) if evaluated else None,
        "reproduced_failure": document.get("reproduced_failure") is True,
    }
    if isinstance(error, dict) and status == "error":
        payload["error"] = {
            "title": error.get("title"),
            "message": error.get("message"),
        }
    return payload


def replay_exit_code(report: dict[str, object]) -> int:
    status = report.get("status")
    if status == "matched":
        return 0
    if status == "diverged":
        return 1
    return 2


def _read_lock(attempt_dir: Path) -> dict[str, object]:
    path = attempt_dir / "lock.json"
    if not path.is_file():
        raise ReplayRejection(
            "replay_source_invalid",
            "source lock.json is missing",
            location="--run",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReplayRejection(
            "replay_source_invalid",
            "source lock.json is not readable",
            location="--run",
        ) from exc
    if not isinstance(raw, dict):
        raise ReplayRejection(
            "replay_source_invalid",
            "source lock.json is not an object",
            location="--run",
        )
    return raw
