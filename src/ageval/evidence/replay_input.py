"""Replay input manifest for a retained Attempt.

The manifest is the executable reading of ``activity.jsonl``. It records task
and image identity, tool semantics, and each terminal action's arguments. A
redacted or missing command stays non-replayable. This module does not start
an environment and does not substitute recorded stdout for a new execution.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import ACTIVITY_LOG_REL, REPLAY_INPUT_REL

REPLAY_INPUT_FORMAT = "ageval.replay.input/1"
REPLAY_PROVENANCE_FORMAT = "ageval.replay/1"
REPLAY_REPORT_FORMAT = "ageval.replay.report/1"
COMPARATOR_ID = "exit_and_normalized_output"
REDACTED_MARK = "[REDACTED"
TOOL_SEMANTICS_BASH = "bash"
TOOL_SEMANTICS_VERSION = "miniswe.bash/1"

_HARD_IDENTITY = ("task_id", "dataset_id", "environment")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_DURATION = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ms|msec|milliseconds|s|sec|secs|seconds|m|min|mins|minutes)\b",
    re.IGNORECASE,
)
_PID = re.compile(r"\b(?:pid|PID)[:\s=#]+\d+\b")

Classify = Callable[[Sequence[Mapping[str, object]]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class ReplayDiagnosis:
    """Preflight result. ``error`` is set only when the source cannot be read."""

    replayable: bool
    missing: tuple[str, ...]
    mismatches: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest: Mapping[str, object]
    error: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "format": REPLAY_INPUT_FORMAT,
            "replayable": self.replayable,
            "missing": list(self.missing),
            "mismatches": list(self.mismatches),
            "warnings": list(self.warnings),
            "manifest": dict(self.manifest),
        }
        if self.error:
            payload["error"] = self.error
        if self.message:
            payload["message"] = self.message
        return payload


def identities_from_lock(lock: Mapping[str, object]) -> dict[str, str]:
    """Task, package, and image identity a replay must reconstruct."""
    overlay = lock.get("job_overlay")
    options: Mapping[str, object] = {}
    if isinstance(overlay, Mapping):
        raw = overlay.get("environment_options")
        if isinstance(raw, Mapping):
            options = raw
    image = _text(options.get("image")) or _text(options.get("docker_image"))
    refs = lock.get("resolved_references")
    if not image and isinstance(refs, Mapping):
        image = _text(refs.get("docker_image")) or _text(refs.get("agent_image"))
    return {
        "task_id": _text(lock.get("task_id")),
        "dataset_id": _text(lock.get("dataset_id")),
        "dataset_version": _text(lock.get("dataset_version")),
        "environment": _text(lock.get("environment")),
        "locked_config_digest": _text(lock.get("digest")),
        "eval_digest": _text(lock.get("eval_digest")),
        "image": image,
    }


def pair_tool_calls(
    records: Sequence[object],
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    """Pair each tool start with its completion, in log order.

    Two starts open at once are ``concurrent_actions``. A start with no
    completion is left incomplete rather than dropped.
    """
    missing: list[str] = []
    open_ids: list[str] = []
    started: dict[str, Mapping[str, object]] = {}
    finished: dict[str, Mapping[str, object]] = {}
    order: list[str] = []
    for record in records:
        kind = getattr(record, "kind", None)
        status = getattr(record, "status", None)
        payload = getattr(record, "payload", None)
        if kind != "tool_call" or not isinstance(payload, Mapping):
            continue
        call_id = _text(payload.get("tool_call_id"))
        if not call_id:
            missing.append("tool_call_id_missing")
            continue
        if status == "in_flight":
            if open_ids and "concurrent_actions" not in missing:
                missing.append("concurrent_actions")
            if call_id not in started:
                order.append(call_id)
            started[call_id] = payload
            if call_id not in open_ids:
                open_ids.append(call_id)
        elif status == "completed" and call_id in started:
            finished[call_id] = payload
            if call_id in open_ids:
                open_ids.remove(call_id)
    pairs: list[dict[str, object]] = []
    for call_id in order:
        start = started[call_id]
        done = finished.get(call_id)
        arguments = start.get("arguments")
        timeout = start.get("timeout_sec")
        exit_code = done.get("exit_code") if isinstance(done, Mapping) else None
        pairs.append(
            {
                "tool_call_id": call_id,
                "tool_name": _text(start.get("tool_name")),
                "tool_kind": _text(start.get("tool_kind")),
                "arguments": dict(arguments) if isinstance(arguments, Mapping) else {},
                "timeout_sec": float(timeout)
                if isinstance(timeout, int | float) and not isinstance(timeout, bool)
                else None,
                "completed": done is not None,
                "recorded_exit_code": exit_code
                if isinstance(exit_code, int) and not isinstance(exit_code, bool)
                else None,
                "recorded_output": done.get("content")
                if isinstance(done, Mapping) and isinstance(done.get("content"), str)
                else "",
            }
        )
    return pairs, tuple(dict.fromkeys(missing))


def unsupported_classification(
    pairs: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Executor that has no terminal-action adapter."""
    del pairs
    return {
        "tool_semantics": "",
        "tool_semantics_version": "",
        "actions": [],
        "missing": ["terminal_replay_unsupported"],
    }


def build_replay_input(
    records: Sequence[object],
    identities: Mapping[str, str],
    classifier: Classify,
) -> dict[str, object]:
    """Build ``ageval.replay.input/1`` without reading or writing a box."""
    pairs, pair_missing = pair_tool_calls(records)
    classified = classifier(pairs)
    actions = classified.get("actions")
    action_rows = [dict(item) for item in actions] if isinstance(actions, Sequence) else []
    missing = list(pair_missing)
    extra = classified.get("missing")
    if isinstance(extra, Sequence) and not isinstance(extra, str):
        missing.extend(str(item) for item in extra if str(item))
    for row in action_rows:
        row_missing = row.get("missing")
        if isinstance(row_missing, Sequence) and not isinstance(row_missing, str):
            missing.extend(str(item) for item in row_missing if str(item))
        if row.get("executable") is not True:
            token = "action_not_executable"
            if token not in missing:
                missing.append(token)
    if not action_rows and "terminal_replay_unsupported" not in missing:
        missing.append("no_terminal_actions")
    warnings: list[str] = []
    if not identities.get("eval_digest"):
        warnings.append("eval_digest_unrecorded")
    deduped = tuple(dict.fromkeys(missing))
    return {
        "format": REPLAY_INPUT_FORMAT,
        "replayable": not deduped and bool(action_rows),
        "missing": list(deduped),
        "warnings": warnings,
        "identities": dict(identities),
        "tool_semantics": _text(classified.get("tool_semantics")),
        "tool_semantics_version": _text(classified.get("tool_semantics_version")),
        "actions": action_rows,
    }


def write_replay_input(attempt_dir: Path, document: Mapping[str, object]) -> Path:
    path = attempt_dir / REPLAY_INPUT_REL
    path.write_text(
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def read_replay_input(attempt_dir: Path) -> dict[str, object] | None:
    path = attempt_dir / REPLAY_INPUT_REL
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("format") != REPLAY_INPUT_FORMAT:
        return None
    return raw


def compare_identities(
    source: Mapping[str, str],
    current: Mapping[str, str],
    *,
    source_semantics: str = "",
    current_semantics: str = "",
) -> tuple[str, ...]:
    """Fields that must match before a fresh environment starts."""
    mismatches: list[str] = []
    for key in _HARD_IDENTITY:
        if source.get(key) != current.get(key):
            mismatches.append(key)
    source_image = source.get("image") or ""
    current_image = current.get("image") or ""
    if source_image != current_image and (source_image or current_image):
        mismatches.append("image")
    source_digest = source.get("eval_digest") or ""
    current_digest = current.get("eval_digest") or ""
    if source_digest and current_digest and source_digest != current_digest:
        mismatches.append("eval_digest")
    if source_semantics and current_semantics and source_semantics != current_semantics:
        mismatches.append("tool_semantics_version")
    return tuple(mismatches)


def diagnose_replay(
    attempt_dir: Path,
    current: Mapping[str, str],
    classifier: Classify,
) -> ReplayDiagnosis:
    """Read retained activity and refuse before any replay effect."""
    activity_path = attempt_dir / ACTIVITY_LOG_REL
    persisted = read_replay_input(attempt_dir)
    if persisted is None and not activity_path.is_file():
        return ReplayDiagnosis(
            replayable=False,
            missing=("recovery_state_missing",),
            mismatches=(),
            warnings=(),
            manifest={},
            error="recovery_state_missing",
            message="activity.jsonl and replay-input.json were not retained",
        )
    log = ActivityLog.open(activity_path) if activity_path.is_file() else None
    if log is not None and log.corrupt:
        return ReplayDiagnosis(
            replayable=False,
            missing=("activity_log_corrupt",),
            mismatches=(),
            warnings=(),
            manifest=persisted or {},
            error="activity_log_corrupt",
            message=log.corrupt,
        )
    if persisted is None:
        assert log is not None
        source_ids = identities_from_lock(_lock_or_empty(attempt_dir))
        persisted = build_replay_input(log.records, source_ids, classifier)
    source_ids = persisted.get("identities")
    identities = source_ids if isinstance(source_ids, Mapping) else {}
    typed = {str(key): _text(value) for key, value in identities.items()}
    mismatches = compare_identities(
        typed,
        current,
        source_semantics=_text(persisted.get("tool_semantics_version")),
        current_semantics=_classifier_version(classifier),
    )
    missing = _string_list(persisted.get("missing"))
    warnings = _string_list(persisted.get("warnings"))
    replayable = persisted.get("replayable") is True and not mismatches
    message = None
    error = None
    if not replayable:
        error = (
            mismatches[0] if mismatches else (missing[0] if missing else "replay_not_replayable")
        )
        message = _diagnosis_message(error, missing, mismatches)
    return ReplayDiagnosis(
        replayable=replayable,
        missing=tuple(missing),
        mismatches=mismatches,
        warnings=tuple(warnings),
        manifest=persisted,
        error=error,
        message=message,
    )


def normalize_output(text: str) -> str:
    """Drop timestamp, duration, and pid tokens. Other text stays."""
    out = _TIME.sub("<time>", text)
    out = _DURATION.sub("<duration>", out)
    return _PID.sub("<pid>", out)


def action_divergence(
    planned: Mapping[str, object],
    observed_exit: int,
    observed_output: str,
) -> dict[str, object] | None:
    """First meaningful difference for one executed action, or None."""
    recorded_exit = planned.get("recorded_exit_code")
    if (
        isinstance(recorded_exit, int)
        and not isinstance(recorded_exit, bool)
        and recorded_exit != observed_exit
    ):
        return {
            "ordinal": planned.get("ordinal"),
            "tool_call_id": planned.get("tool_call_id"),
            "field": "exit_code",
            "recorded_exit_code": recorded_exit,
            "observed_exit_code": observed_exit,
        }
    recorded_output = planned.get("recorded_output")
    if isinstance(recorded_output, str) and normalize_output(recorded_output) != normalize_output(
        observed_output
    ):
        return {
            "ordinal": planned.get("ordinal"),
            "tool_call_id": planned.get("tool_call_id"),
            "field": "output",
            "recorded_exit_code": recorded_exit
            if isinstance(recorded_exit, int) and not isinstance(recorded_exit, bool)
            else None,
            "observed_exit_code": observed_exit,
        }
    return None


def _classifier_version(classifier: Classify) -> str:
    sample = classifier(())
    return _text(sample.get("tool_semantics_version"))


def _diagnosis_message(
    error: str,
    missing: Sequence[str],
    mismatches: Sequence[str],
) -> str:
    if mismatches:
        return "initial inputs differ: " + ", ".join(mismatches)
    if missing:
        return "replay input is incomplete: " + ", ".join(missing)
    return error


def _lock_or_empty(attempt_dir: Path) -> dict[str, object]:
    path = attempt_dir / "lock.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [str(item) for item in value if str(item)]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def command_redacted(command: str) -> bool:
    return REDACTED_MARK in command
