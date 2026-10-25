"""Append-only Attempt activity log (``ageval.activity/1``).

The parent process is the only writer. Every line is redacted, flushed, and
fsynced. A truncated final line is dropped. A broken line anywhere earlier
marks the log corrupt so recovery can seal ``activity_log_corrupt`` instead of
replaying a hole.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from ageval.config.errors import ERROR_INVALID_FORMAT, ConfigError
from ageval.evidence.redaction import redact_and_assert

ACTIVITY_FORMAT = "ageval.activity/1"

KINDS = frozenset(
    {
        "attempt",
        "session",
        "invoke",
        "model_turn",
        "tool_call",
        "compaction",
        "phase",
    }
)
STATUSES = frozenset({"in_flight", "completed", "aborted"})

# ``tool_call`` may be ``aborted`` when a replay-safe call is sent again.
_ALLOWED_STATUS: dict[str, frozenset[str]] = {
    "attempt": frozenset({"completed"}),
    "session": frozenset({"completed"}),
    "invoke": frozenset({"in_flight", "completed"}),
    "model_turn": frozenset({"in_flight", "completed", "aborted"}),
    "tool_call": frozenset({"in_flight", "completed", "aborted"}),
    "compaction": frozenset({"in_flight", "completed"}),
    "phase": frozenset({"in_flight", "completed"}),
}

_REQUIRED: dict[tuple[str, str], frozenset[str]] = {
    ("attempt", "completed"): frozenset(
        {
            "run_id",
            "trial_id",
            "attempt_id",
            "task_id",
            "attempt_index",
            "suite_run_id",
            "locked_config_digest",
            "environment_kind",
            "environment_nonce",
            "environment_handle",
        }
    ),
    ("session", "completed"): frozenset(
        {
            "session_id",
            "profile_id",
            "actor_id",
            "environment",
            "executor_kind",
            "native_session_id",
        }
    ),
    ("invoke", "in_flight"): frozenset(
        {
            "session_id",
            "turn_index",
            "prompt",
            "tools_digest",
            "messages_digest",
            "explicit_messages",
        }
    ),
    ("invoke", "completed"): frozenset(
        {
            "session_id",
            "turn_index",
            "ok",
            "text",
            "structured",
            "tool_calls",
            "usage",
            "error",
            "checkpoint_seq",
        }
    ),
    ("model_turn", "in_flight"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "step_index",
            "delta_messages",
            "system_section_deltas",
        }
    ),
    ("model_turn", "completed"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "step_index",
            "assistant_text",
            "thought",
            "tool_calls",
            "usage",
            "stop_reason",
        }
    ),
    ("model_turn", "aborted"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "step_index",
            "partial_text",
            "partial_thought",
            "reason",
        }
    ),
    ("tool_call", "in_flight"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "tool_call_id",
            "tool_name",
            "tool_kind",
            "arguments",
            "replay_safe",
            "system_effect",
            "timeout_sec",
            "deadline_utc",
        }
    ),
    ("tool_call", "completed"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "tool_call_id",
            "outcome",
            "exit_code",
            "content",
            "stderr",
            "raw_output",
            "checkpoint_seq",
        }
    ),
    ("tool_call", "aborted"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "tool_call_id",
            "reason",
        }
    ),
    ("compaction", "in_flight"): frozenset({"session_id", "invoke_request_id", "source"}),
    ("compaction", "completed"): frozenset(
        {
            "session_id",
            "invoke_request_id",
            "source",
            "replaces_through_seq",
            "summary_messages",
            "native_journal_rel",
            "usage",
            "checkpoint_seq",
        }
    ),
    ("phase", "in_flight"): frozenset({"phase"}),
    ("phase", "completed"): frozenset({"phase", "elapsed_ms", "limit_reached", "checkpoint_seq"}),
}

_HEADER_MUTABLE = frozenset({"environment_handle", "environment_nonce", "environment_kind"})


def _invalid(message: str) -> NoReturn:
    raise ValueError(message)


def _bad_type(message: str) -> NoReturn:
    raise TypeError(message)


def utc_now() -> str:
    """UTC timestamp with millisecond precision and a ``Z`` suffix."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def canonical_digest(value: Any) -> str:
    """Stable ``sha256:`` digest of a JSON value. ``None`` digests as ``null``."""
    if value is None:
        raw = b"null"
    else:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    """One validated ``activity.jsonl`` line."""

    format: str
    seq: int
    at: str
    request_id: str
    kind: str
    status: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "seq": self.seq,
            "at": self.at,
            "request_id": self.request_id,
            "kind": self.kind,
            "status": self.status,
            "payload": self.payload,
        }


class ActivityLog:
    """Reader and sole writer for one Attempt's ``activity.jsonl``."""

    def __init__(self, path: Path, *, sentinels: Iterable[str] = ()) -> None:
        self.path = path
        self.sentinels = tuple(s for s in sentinels if s)
        self.records: list[ActivityRecord] = []
        self.facts: list[str] = []
        self.corrupt: str | None = None
        self._next_seq = 1
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: Path, *, sentinels: Iterable[str] = ()) -> ActivityLog:
        log = cls(path, sentinels=sentinels)
        log._load()
        return log

    @property
    def is_empty(self) -> bool:
        return not self.records and self.corrupt is None

    def header(self) -> ActivityRecord | None:
        for record in self.records:
            if record.seq == 1 and record.kind == "attempt":
                return record
        return None

    def append(
        self,
        *,
        request_id: str,
        kind: str,
        status: str,
        payload: Mapping[str, Any],
        prepare: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> ActivityRecord:
        """Append one line. ``prepare(seq)`` may capture a checkpoint first.

        The line is written only after ``prepare`` returns. A failure there
        leaves the log unchanged.
        """
        cleaned = self._clean_payload(kind, status, payload)
        with self._lock:
            seq = self._next_seq
            if prepare is not None:
                extra = prepare(seq)
                if extra:
                    merged = dict(cleaned)
                    merged.update(dict(extra))
                    cleaned = self._clean_payload(kind, status, merged)
            record = ActivityRecord(
                format=ACTIVITY_FORMAT,
                seq=seq,
                at=utc_now(),
                request_id=request_id,
                kind=kind,
                status=status,
                payload=cleaned,
            )
            self._write_line(record)
            self.records.append(record)
            self._next_seq = seq + 1
            return record

    def update_attempt_header(self, **fields: Any) -> ActivityRecord:
        """Rewrite the seq-1 attempt line after the environment handle is known."""
        unknown = set(fields) - _HEADER_MUTABLE
        if unknown:
            _invalid(f"attempt header fields are fixed: {sorted(unknown)}")
        with self._lock:
            header = self.header()
            if header is None:
                _invalid("activity log has no attempt header")
            payload = dict(header.payload)
            payload.update(fields)
            cleaned = self._clean_payload("attempt", "completed", payload)
            updated = ActivityRecord(
                format=header.format,
                seq=header.seq,
                at=header.at,
                request_id=header.request_id,
                kind=header.kind,
                status=header.status,
                payload=cleaned,
            )
            self.records[0] = updated
            self._rewrite_all()
            return updated

    def has_completed_phase(self, phase: str) -> bool:
        return any(
            record.kind == "phase"
            and record.status == "completed"
            and record.payload.get("phase") == phase
            for record in self.records
        )

    def has_phase_status(self, phase: str, status: str) -> bool:
        return any(
            record.kind == "phase"
            and record.status == status
            and record.payload.get("phase") == phase
            for record in self.records
        )

    def records_for(self, *, kind: str, request_id: str) -> list[ActivityRecord]:
        return [
            record
            for record in self.records
            if record.kind == kind and record.request_id == request_id
        ]

    def latest_status(self, *, kind: str, request_id: str) -> str | None:
        found = self.records_for(kind=kind, request_id=request_id)
        if not found:
            return None
        return found[-1].status

    def admitted_run_invoke_count(self) -> int:
        """Invokes admitted before ``seal_run`` completed. In-flight counts once."""
        seal_seq = self._seal_run_seq()
        seen: set[str] = set()
        for record in self.records:
            if record.kind != "invoke":
                continue
            if record.status not in {"in_flight", "completed"}:
                continue
            if seal_seq is not None and record.seq > seal_seq:
                continue
            seen.add(record.request_id)
        return len(seen)

    def invoke_already_admitted(self, request_id: str) -> bool:
        return any(
            record.kind == "invoke" and record.request_id == request_id for record in self.records
        )

    def phase_elapsed_ms(self, phase: str) -> float:
        """Active milliseconds already spent in ``phase``, from the log."""
        best = 0.0
        in_phase = False
        for record in self.records:
            if record.kind == "phase" and record.payload.get("phase") == phase:
                if record.status == "in_flight":
                    in_phase = True
                elif record.status == "completed":
                    best = max(best, _float_or_zero(record.payload.get("elapsed_ms")))
                    in_phase = False
                continue
            if in_phase:
                best = max(best, _float_or_zero(record.payload.get("elapsed_ms")))
        return best

    def last_checkpoint_seq(self) -> int | None:
        best: int | None = None
        for record in self.records:
            if record.status != "completed":
                continue
            raw = record.payload.get("checkpoint_seq")
            if isinstance(raw, int) and not isinstance(raw, bool):
                best = raw if best is None else max(best, raw)
        return best

    def last_completed_env_seq(self) -> int | None:
        """Activity seq of the last line that published a checkpoint cursor."""
        return self.last_checkpoint_seq()

    def inflight_tool_deadline(self) -> str | None:
        step = self.open_inflight(kinds=frozenset({"tool_call"}))
        if step is None:
            return None
        raw = step.payload.get("deadline_utc")
        return raw if isinstance(raw, str) and raw else None

    def matches_inflight_tool(self, request_id: str) -> bool:
        return self.latest_status(kind="tool_call", request_id=request_id) == "in_flight"

    def open_inflight(
        self,
        *,
        kinds: frozenset[str],
        session_id: str | None = None,
        invoke_request_id: str | None = None,
    ) -> ActivityRecord | None:
        """Latest in-flight step of ``kinds`` that has no later terminal line."""
        terminal: set[str] = set()
        for record in self.records:
            if record.kind not in kinds:
                continue
            if record.status in {"completed", "aborted"}:
                terminal.add(record.request_id)
        chosen: ActivityRecord | None = None
        for record in self.records:
            if record.kind not in kinds or record.status != "in_flight":
                continue
            if record.request_id in terminal:
                continue
            if session_id is not None and record.payload.get("session_id") != session_id:
                continue
            if invoke_request_id is not None:
                if record.kind == "invoke" and record.request_id != invoke_request_id:
                    continue
                if record.kind != "invoke" and record.payload.get("invoke_request_id") != (
                    invoke_request_id
                ):
                    continue
            chosen = record
        return chosen

    def completed_system_effect_tools(self) -> list[ActivityRecord]:
        out: list[ActivityRecord] = []
        for record in self.records:
            if record.kind != "tool_call" or record.status != "completed":
                continue
            if record.payload.get("system_effect") is True:
                out.append(record)
        return out

    def session_record(self, session_id: str) -> ActivityRecord | None:
        for record in self.records:
            if record.kind == "session" and record.payload.get("session_id") == session_id:
                return record
        return None

    def _seal_run_seq(self) -> int | None:
        for record in self.records:
            if (
                record.kind == "phase"
                and record.status == "completed"
                and record.payload.get("phase") == "seal_run"
            ):
                return record.seq
        return None

    def _clean_payload(self, kind: str, status: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if kind not in KINDS:
            _invalid(f"unknown activity kind: {kind}")
        allowed = _ALLOWED_STATUS[kind]
        if status not in allowed:
            _invalid(f"{kind} does not allow status {status}")
        cleaned = redact_and_assert(dict(payload), extra_sentinels=self.sentinels)
        if not isinstance(cleaned, dict):
            _bad_type("activity payload must be an object")
        missing = _REQUIRED[(kind, status)] - set(cleaned)
        if missing:
            _invalid(f"activity {kind}/{status} missing {sorted(missing)}")
        return cleaned

    def _load(self) -> None:
        if not self.path.is_file():
            return
        raw = self.path.read_bytes()
        if not raw:
            return
        text = raw.decode("utf-8")
        missing_newline = not text.endswith("\n")
        lines = text.splitlines()
        if missing_newline and lines:
            lines = lines[:-1]
            self._note_truncated()
        parsed: list[ActivityRecord] = []
        for index, line in enumerate(lines):
            if not line.strip():
                self.corrupt = f"blank activity line {index + 1}"
                self.records = parsed
                self._next_seq = len(parsed) + 1
                return
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                if index == len(lines) - 1:
                    self._note_truncated()
                    break
                self.corrupt = f"activity line {index + 1} is not json"
                self.records = parsed
                self._next_seq = len(parsed) + 1
                return
            if not isinstance(obj, dict):
                self.corrupt = f"activity line {index + 1} is not an object"
                self.records = parsed
                self._next_seq = len(parsed) + 1
                return
            try:
                record = _parse_record(obj)
            except ConfigError:
                raise
            except (TypeError, ValueError) as exc:
                self.corrupt = str(exc)
                self.records = parsed
                self._next_seq = len(parsed) + 1
                return
            if record.seq != len(parsed) + 1:
                self.corrupt = f"activity seq {record.seq} is not {len(parsed) + 1}"
                self.records = parsed
                self._next_seq = len(parsed) + 1
                return
            parsed.append(record)
        self.records = parsed
        self._next_seq = len(parsed) + 1

    def _note_truncated(self) -> None:
        if "recovery_tail_truncated" not in self.facts:
            self.facts.append("recovery_tail_truncated")

    def _write_line(self, record: ActivityRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.as_dict(), sort_keys=True, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _rewrite_all(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + f".tmp.{os.getpid()}")
        body = "".join(
            json.dumps(record.as_dict(), sort_keys=True, ensure_ascii=False, default=str) + "\n"
            for record in self.records
        )
        tmp.write_text(body, encoding="utf-8")
        with tmp.open("a", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)


def _parse_record(obj: Mapping[str, Any]) -> ActivityRecord:
    if obj.get("format") != ACTIVITY_FORMAT:
        msg = f"activity format must be {ACTIVITY_FORMAT}"
        raise ConfigError(ERROR_INVALID_FORMAT, msg, location="/format")
    kind = obj.get("kind")
    status = obj.get("status")
    if not isinstance(kind, str) or kind not in KINDS:
        _invalid(f"unknown activity kind: {kind!r}")
    if not isinstance(status, str) or status not in _ALLOWED_STATUS[kind]:
        _invalid(f"{kind} does not allow status {status!r}")
    seq = obj.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        _invalid(f"activity seq must be a positive int, got {seq!r}")
    request_id = obj.get("request_id")
    at = obj.get("at")
    payload = obj.get("payload")
    if not isinstance(request_id, str) or not request_id:
        _invalid("activity request_id is required")
    if not isinstance(at, str) or not at:
        _invalid("activity at is required")
    if not isinstance(payload, dict):
        _bad_type("activity payload must be an object")
    missing = _REQUIRED[(kind, status)] - set(payload)
    if missing:
        _invalid(f"activity {kind}/{status} missing {sorted(missing)}")
    return ActivityRecord(
        format=ACTIVITY_FORMAT,
        seq=seq,
        at=at,
        request_id=request_id,
        kind=kind,
        status=status,
        payload=payload,
    )


def _float_or_zero(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def project_messages(records: list[ActivityRecord], session_id: str) -> list[dict[str, Any]]:
    """Fold one session's log into a message list, honoring compaction."""
    session = [record for record in records if record.payload.get("session_id") == session_id]
    skip_through = 0
    out: list[dict[str, Any]] = []
    compactions = [
        record for record in session if record.kind == "compaction" and record.status == "completed"
    ]
    if compactions:
        last = compactions[-1]
        raw_skip = last.payload.get("replaces_through_seq")
        if isinstance(raw_skip, int) and not isinstance(raw_skip, bool):
            skip_through = raw_skip
        summary = last.payload.get("summary_messages")
        if isinstance(summary, list):
            out.extend(dict(item) for item in summary if isinstance(item, dict))
    inflight_delta = {
        record.request_id: record
        for record in session
        if record.kind == "model_turn" and record.status == "in_flight"
    }
    for record in session:
        if record.seq <= skip_through or record.status != "completed":
            continue
        if record.kind == "model_turn":
            delta = inflight_delta.get(record.request_id)
            if delta is not None:
                messages = delta.payload.get("delta_messages")
                if isinstance(messages, list):
                    out.extend(dict(item) for item in messages if isinstance(item, dict))
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": record.payload.get("assistant_text") or "",
            }
            thought = record.payload.get("thought")
            if isinstance(thought, str) and thought:
                assistant["thought"] = thought
            calls = record.payload.get("tool_calls")
            if isinstance(calls, list) and calls:
                assistant["tool_calls"] = calls
            out.append(assistant)
        elif record.kind == "tool_call":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": record.payload.get("tool_call_id"),
                    "content": record.payload.get("content") or "",
                }
            )
    return out


class ActivityScope:
    """Per-invoke view an executor uses to log steps and project context."""

    def __init__(
        self,
        log: ActivityLog,
        *,
        session_id: str,
        invoke_request_id: str,
        environment_reattached: bool = False,
    ) -> None:
        self.log = log
        self.session_id = session_id
        self.invoke_request_id = invoke_request_id
        self.environment_reattached = environment_reattached

    def record_model_turn_in_flight(
        self,
        step_index: int,
        delta_messages: list[dict[str, Any]],
        *,
        system_section_deltas: dict[str, Any] | None = None,
    ) -> ActivityRecord:
        return self.log.append(
            request_id=f"mt_{self.invoke_request_id}_{step_index}",
            kind="model_turn",
            status="in_flight",
            payload={
                "session_id": self.session_id,
                "invoke_request_id": self.invoke_request_id,
                "step_index": step_index,
                "delta_messages": delta_messages,
                "system_section_deltas": system_section_deltas,
            },
        )

    def record_model_turn_completed(
        self,
        step_index: int,
        *,
        assistant_text: str,
        thought: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        stop_reason: str | None = None,
    ) -> ActivityRecord:
        return self.log.append(
            request_id=f"mt_{self.invoke_request_id}_{step_index}",
            kind="model_turn",
            status="completed",
            payload={
                "session_id": self.session_id,
                "invoke_request_id": self.invoke_request_id,
                "step_index": step_index,
                "assistant_text": assistant_text,
                "thought": thought,
                "tool_calls": list(tool_calls or []),
                "usage": usage,
                "stop_reason": stop_reason,
            },
        )

    def record_model_turn_aborted(
        self,
        step_index: int,
        *,
        partial_text: str = "",
        partial_thought: str | None = None,
        reason: str,
    ) -> ActivityRecord:
        return self.log.append(
            request_id=f"mt_{self.invoke_request_id}_{step_index}",
            kind="model_turn",
            status="aborted",
            payload={
                "session_id": self.session_id,
                "invoke_request_id": self.invoke_request_id,
                "step_index": step_index,
                "partial_text": partial_text,
                "partial_thought": partial_thought,
                "reason": reason,
            },
        )

    def record_tool_call_in_flight(
        self,
        tool_call_id: str,
        tool_name: str,
        tool_kind: str,
        arguments: Mapping[str, Any],
        *,
        replay_safe: bool = False,
        system_effect: bool = False,
        timeout_sec: float | None = None,
        deadline_utc: str | None = None,
        request_id: str | None = None,
    ) -> ActivityRecord:
        return self.log.append(
            request_id=request_id or f"tool_{self.session_id}_{tool_call_id}",
            kind="tool_call",
            status="in_flight",
            payload={
                "session_id": self.session_id,
                "invoke_request_id": self.invoke_request_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "tool_kind": tool_kind,
                "arguments": dict(arguments),
                "replay_safe": replay_safe,
                "system_effect": system_effect,
                "timeout_sec": timeout_sec,
                "deadline_utc": deadline_utc,
            },
        )

    def record_tool_call_completed(
        self,
        tool_call_id: str,
        *,
        outcome: str,
        exit_code: int | None,
        content: str,
        stderr: str | None = None,
        raw_output: Any = None,
        checkpoint_seq: int | None = None,
        request_id: str | None = None,
        prepare: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> ActivityRecord:
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "invoke_request_id": self.invoke_request_id,
            "tool_call_id": tool_call_id,
            "outcome": outcome,
            "exit_code": exit_code,
            "content": content,
            "stderr": stderr,
            "raw_output": raw_output,
            "checkpoint_seq": checkpoint_seq,
        }
        return self.log.append(
            request_id=request_id or f"tool_{self.session_id}_{tool_call_id}",
            kind="tool_call",
            status="completed",
            payload=payload,
            prepare=prepare,
        )

    def record_compaction(
        self,
        *,
        source: str,
        replaces_through_seq: int | None = None,
        summary_messages: list[dict[str, Any]] | None = None,
        native_journal_rel: str | None = None,
        usage: dict[str, Any] | None = None,
        checkpoint_seq: int | None = None,
        prepare: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> ActivityRecord:
        request_id = f"cmp_{self.session_id}_{self.invoke_request_id}"
        self.log.append(
            request_id=request_id,
            kind="compaction",
            status="in_flight",
            payload={
                "session_id": self.session_id,
                "invoke_request_id": self.invoke_request_id,
                "source": source,
            },
        )
        return self.log.append(
            request_id=request_id,
            kind="compaction",
            status="completed",
            payload={
                "session_id": self.session_id,
                "invoke_request_id": self.invoke_request_id,
                "source": source,
                "replaces_through_seq": replaces_through_seq,
                "summary_messages": summary_messages,
                "native_journal_rel": native_journal_rel,
                "usage": usage,
                "checkpoint_seq": checkpoint_seq,
            },
            prepare=prepare,
        )

    def completed_steps(self) -> list[ActivityRecord]:
        return [
            record
            for record in self.log.records
            if record.status == "completed"
            and record.payload.get("session_id") == self.session_id
            and (
                record.kind == "invoke"
                and record.request_id == self.invoke_request_id
                or record.payload.get("invoke_request_id") == self.invoke_request_id
            )
        ]

    def inflight_step(self) -> ActivityRecord | None:
        return self.log.open_inflight(
            kinds=frozenset({"model_turn", "tool_call"}),
            session_id=self.session_id,
            invoke_request_id=self.invoke_request_id,
        )

    def mark_aborted(self, request_id: str, *, reason: str) -> ActivityRecord:
        inflight = None
        for record in self.log.records:
            if record.request_id == request_id and record.status == "in_flight":
                inflight = record
        if inflight is None:
            _invalid(f"no in-flight activity record {request_id}")
        if inflight.kind == "model_turn":
            return self.record_model_turn_aborted(
                int(inflight.payload.get("step_index") or 0),
                partial_text=str(inflight.payload.get("partial_text") or ""),
                partial_thought=inflight.payload.get("partial_thought")
                if isinstance(inflight.payload.get("partial_thought"), str)
                else None,
                reason=reason,
            )
        if inflight.kind == "tool_call":
            return self.log.append(
                request_id=request_id,
                kind="tool_call",
                status="aborted",
                payload={
                    "session_id": self.session_id,
                    "invoke_request_id": self.invoke_request_id,
                    "tool_call_id": str(inflight.payload.get("tool_call_id") or ""),
                    "reason": reason,
                },
            )
        _invalid(f"cannot abort activity kind {inflight.kind}")

    def project_messages(self) -> list[dict[str, Any]]:
        return project_messages(self.log.records, self.session_id)


def reconcile_inflight_tail(
    scope: ActivityScope,
    *,
    partial_output: str | None = None,
    prepare: Callable[[int], Mapping[str, Any]] | None = None,
) -> None:
    """Close a cut-off step before the executor continues.

    A cut-off model turn is aborted and sent again. A replay-safe tool is
    aborted so the executor may re-run it. Any other cut-off tool completes
    as ``interrupted`` and is not executed again.
    """
    inflight = scope.inflight_step()
    if inflight is None:
        return
    if inflight.kind == "model_turn":
        scope.mark_aborted(inflight.request_id, reason="process_interrupted")
        return
    if inflight.kind != "tool_call":
        return
    if inflight.payload.get("replay_safe") is True:
        scope.mark_aborted(inflight.request_id, reason="rerun_replay_safe")
        return
    content = partial_output or "[tool execution interrupted by process restart]"
    scope.record_tool_call_completed(
        str(inflight.payload.get("tool_call_id") or ""),
        outcome="interrupted",
        exit_code=None,
        content=content,
        request_id=inflight.request_id,
        prepare=prepare,
    )
