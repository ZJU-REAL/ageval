"""Classify retained checkpoints as forkable run-phase cuts.

A forkable cut is one completed run-phase snapshot before solver sealing and
before gold is uploaded, from a single session whose executor can continue.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ageval.evidence.activity import ActivityLog, ActivityRecord
from ageval.evidence.checkpoints import CHECKPOINT_FORMAT
from ageval.evidence.store import ACTIVITY_LOG_REL, CHECKPOINTS_DIR_REL

FORK_CONTINUATION_KINDS = frozenset({"miniswe", "terminus-2", "openai-http", "anthropic-http"})
_LIFECYCLE_PHASES = frozenset({"environment", "run", "evaluate", "record"})
_MANIFEST_NAME = re.compile(r"^seq_(\d{6})\.json$")
_EFFECT_KINDS = frozenset({"invoke", "model_turn", "tool_call", "compaction"})


@dataclass(frozen=True)
class CheckpointCut:
    seq: int
    phase: str
    forkable: bool
    state: str
    reason: str | None
    kind: str | None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "seq": self.seq,
            "phase": self.phase,
            "forkable": self.forkable,
            "state": self.state,
            "kind": self.kind,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class CheckpointListing:
    attempt_id: str
    retained: bool
    error: str | None
    message: str | None
    cuts: tuple[CheckpointCut, ...]

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "format": "ageval.checkpoints/1",
            "attempt_id": self.attempt_id,
            "ok": self.error is None,
            "retained": self.retained,
            "checkpoints": [cut.as_dict() for cut in self.cuts],
        }
        if self.error is not None:
            payload["error"] = self.error
        if self.message is not None:
            payload["message"] = self.message
        return payload


def fork_marker(result: object, summary: object) -> dict[str, object] | None:
    """Projection for list and detail views. Uses the child document only."""
    raw = _fork_doc(result) or _fork_doc(summary)
    if raw is None and isinstance(summary, dict):
        raw = _fork_doc(summary.get("result"))
    if raw is None:
        return None
    parent = raw.get("parent_attempt_id")
    if not isinstance(parent, str) or not parent.strip():
        return None
    seq = raw.get("checkpoint_seq")
    source = raw.get("source_model")
    continuation = raw.get("continuation_model")
    return {
        "parent_attempt_id": parent,
        "checkpoint_seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        "source_model": source if isinstance(source, str) else "",
        "continuation_model": continuation if isinstance(continuation, str) else "",
    }


def _fork_doc(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    fork = value.get("fork")
    if isinstance(fork, dict) and fork.get("parent_attempt_id"):
        return fork
    return None


def list_fork_cuts(attempt_dir: Path, *, attempt_id: str) -> CheckpointListing:
    """Classify manifests under one Attempt. Does not start an environment."""
    activity_path = attempt_dir / ACTIVITY_LOG_REL
    checkpoints = attempt_dir / CHECKPOINTS_DIR_REL
    if not activity_path.is_file() or not checkpoints.is_dir():
        return CheckpointListing(
            attempt_id=attempt_id,
            retained=False,
            error="recovery_state_missing",
            message="activity.jsonl and checkpoints/ must both be retained",
            cuts=(),
        )
    log = ActivityLog.open(activity_path)
    if log.corrupt:
        return CheckpointListing(
            attempt_id=attempt_id,
            retained=True,
            error="activity_log_corrupt",
            message=log.corrupt,
            cuts=(),
        )
    return CheckpointListing(
        attempt_id=attempt_id,
        retained=True,
        error=None,
        message=None,
        cuts=tuple(_classify(log, checkpoints)),
    )


def _classify(log: ActivityLog, checkpoints: Path) -> list[CheckpointCut]:
    records = log.records
    seal_seq = _phase_seq(records, "seal_run", status="completed")
    gold_seq = _phase_seq(records, "evaluate")
    seqs = _listed_seqs(records, checkpoints)
    cuts: list[CheckpointCut] = []
    for seq in seqs:
        phase = _phase_at(records, seq)
        state, manifest_seq = _manifest_state(checkpoints, seq)
        owners = _owners(records, seq)
        kind = owners[0].kind if len(owners) == 1 else None
        reason = _reason(
            records,
            seq,
            phase=phase,
            state=state,
            manifest_seq=manifest_seq,
            owners=owners,
            seal_seq=seal_seq,
            gold_seq=gold_seq,
        )
        cuts.append(
            CheckpointCut(
                seq=seq,
                phase=phase,
                forkable=reason is None and state == "available",
                state=state,
                reason=reason,
                kind=kind,
            )
        )
    return cuts


def _listed_seqs(records: list[ActivityRecord], checkpoints: Path) -> list[int]:
    found: set[int] = set()
    for record in records:
        raw = record.payload.get("checkpoint_seq")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
            found.add(raw)
    if checkpoints.is_dir():
        for path in checkpoints.iterdir():
            match = _MANIFEST_NAME.fullmatch(path.name)
            if match and path.is_file():
                found.add(int(match.group(1)))
    return sorted(found)


def _phase_seq(
    records: list[ActivityRecord],
    phase: str,
    *,
    status: str | None = None,
) -> int | None:
    for record in records:
        if record.kind != "phase" or record.payload.get("phase") != phase:
            continue
        if status is not None and record.status != status:
            continue
        return record.seq
    return None


def _phase_at(records: list[ActivityRecord], seq: int) -> str:
    phase = "unknown"
    for record in records:
        if record.seq > seq:
            break
        if record.kind != "phase":
            continue
        name = record.payload.get("phase")
        if isinstance(name, str) and name in _LIFECYCLE_PHASES:
            phase = name
    return phase


def _owners(records: list[ActivityRecord], seq: int) -> list[ActivityRecord]:
    return [
        record
        for record in records
        if record.seq <= seq and record.payload.get("checkpoint_seq") == seq
    ]


def _sessions_at(records: list[ActivityRecord], seq: int) -> list[ActivityRecord]:
    return [
        record
        for record in records
        if record.kind == "session" and record.status == "completed" and record.seq <= seq
    ]


def _open_inflight(records: list[ActivityRecord], seq: int) -> bool:
    terminal: set[tuple[str, str]] = set()
    for record in records:
        if record.seq > seq or record.kind not in _EFFECT_KINDS:
            continue
        if record.status in {"completed", "aborted"}:
            terminal.add((record.kind, record.request_id))
    for record in records:
        if record.seq > seq or record.kind not in _EFFECT_KINDS:
            continue
        if record.status == "in_flight" and (record.kind, record.request_id) not in terminal:
            return True
    return False


def _reason(
    records: list[ActivityRecord],
    seq: int,
    *,
    phase: str,
    state: str,
    manifest_seq: int | None,
    owners: list[ActivityRecord],
    seal_seq: int | None,
    gold_seq: int | None,
) -> str | None:
    if gold_seq is not None and seq >= gold_seq:
        return "gold_exposed"
    if seal_seq is not None and seq >= seal_seq:
        return "solver_sealed"
    if phase != "run":
        return "not_run_phase"
    sessions = _sessions_at(records, seq)
    if len(sessions) > 1:
        return "multi_session"
    if len(owners) != 1 or owners[0].seq != seq or owners[0].status != "completed":
        if state != "available":
            return "checkpoint_incomplete" if state == "incomplete" else "not_a_completed_cut"
        return "not_a_completed_cut" if not owners else "inconsistent"
    if _open_inflight(records, seq):
        return "inconsistent"
    if manifest_seq is not None and manifest_seq != seq:
        return "inconsistent"
    if state == "missing":
        return "checkpoint_incomplete"
    if state == "incomplete":
        return "state_not_restorable"
    if len(sessions) != 1:
        return "state_not_restorable"
    executor = sessions[0].payload.get("executor_kind")
    if executor not in FORK_CONTINUATION_KINDS:
        return "continuation_unsupported"
    return None


def _manifest_state(checkpoints: Path, seq: int) -> tuple[str, int | None]:
    path = checkpoints / f"seq_{seq:06d}.json"
    if not path.is_file():
        return "missing", None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return "incomplete", None
    if not isinstance(data, dict) or data.get("format") != CHECKPOINT_FORMAT:
        return "incomplete", None
    raw_seq = data.get("seq")
    manifest_seq = raw_seq if isinstance(raw_seq, int) and not isinstance(raw_seq, bool) else None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return "incomplete", manifest_seq
    for meta in entries.values():
        if not isinstance(meta, dict):
            return "incomplete", manifest_seq
        digest = meta.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            return "incomplete", manifest_seq
        blob = checkpoints / "blobs" / digest[:2] / digest
        if not blob.is_file():
            return "incomplete", manifest_seq
    return "available", manifest_seq
