"""Core trajectory writer — consumes ``ageval.trajectory.event/1`` only.

Adapters map vendor-native streams into the neutral event contract; this module
folds those events into turn rows and the engine writes the Attempt's
``trajectory.jsonl`` from them. Observational — never PASS.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ageval.evidence.schema import EVENT_SCHEMA_VERSION

TRAJECTORY_FILENAME = "trajectory.jsonl"
OBSERVATION_FILENAME = "observation.jsonl"
OBSERVATION_REL = "evaluation/observation.jsonl"
_TOOL_PHASES = frozenset({"start", "update"})


def write_attempt_trajectory(
    run_dir: Path,
    turns: list[list[dict[str, Any]]],
    *,
    redaction_sentinels: tuple[str, ...] | list[str] | None = None,
) -> Path:
    """Write the Attempt trajectory: every turn's rows, in invocation order.

    The ``trajectory_seal`` winner writes this file; the engine default is this
    function. Plugins on collect/enrich shape the payloads that produced
    *turns*; they are not the author of the sealed evidence.
    """
    from ageval.evidence.redaction import redact_value

    sentinels = tuple(s for s in (redaction_sentinels or ()) if s)
    rows = [redact_value(row, extra_sentinels=sentinels) for turn in turns for row in turn]
    path = run_dir / TRAJECTORY_FILENAME
    run_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")
    return path


def write_evaluation_observation(
    run_dir: Path,
    turns: list[list[dict[str, Any]]],
    *,
    redaction_sentinels: tuple[str, ...] | list[str] | None = None,
) -> Path:
    """Write evaluate-phase layer C. Observational — never PASS.

    Absent turns must not create the file (no-SDK evaluators stay on the
    result.json + evaluation/ tree).
    """
    from ageval.evidence.redaction import redact_value

    sentinels = tuple(s for s in (redaction_sentinels or ()) if s)
    rows = [redact_value(row, extra_sentinels=sentinels) for turn in turns for row in turn]
    path = run_dir / OBSERVATION_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")
    return path


def turn_rows(
    *,
    prompt: str,
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    final_text: str,
    structured: dict[str, object] | None,
    usage: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
    ok: bool,
    error: str | None,
    metadata: dict[str, Any] | None = None,
    include_user: bool = True,
) -> list[dict[str, Any]]:
    """Fold one invocation's events into turn-level training rows.

    Consumes only events with ``schema == ageval.trajectory.event/1``. Other
    rows are ignored (vendor raw belongs in ``backend_raw/`` / ``events.jsonl``).

    Row order: user → (thought? → tool_call → observation)* →
    assistant (final) → permission* → terminal.

    ``include_user=False`` omits the user row (evaluate-phase observation:
    judge prompts often embed hidden reference text).

    ``profile_id`` on every row is the package role
    (``Agent.session(profile_id)``), not chat ``role``.
    """
    thought_parts: list[str] = []
    assistant_parts: list[str] = []
    thought_timing: dict[str, Any] = {}
    assistant_timing: dict[str, Any] = {}
    permission_events: list[dict[str, Any]] = []
    tool_states: dict[str, dict[str, Any]] = {}
    session_id: str | None = None
    producer: str | None = None
    profile_id: str | None = None
    if isinstance(metadata, dict):
        raw_pid = metadata.get("profile_id")
        if isinstance(raw_pid, str) and raw_pid.strip():
            profile_id = raw_pid.strip()

    for ev in events:
        if not isinstance(ev, dict) or ev.get("schema") != EVENT_SCHEMA_VERSION:
            continue
        sid = ev.get("session_id")
        if isinstance(sid, str) and sid:
            session_id = sid
        src = ev.get("source")
        if isinstance(src, str) and src:
            producer = src

    turn_index = 1
    if isinstance(metadata, dict):
        raw_ti = metadata.get("turn_index")
        if isinstance(raw_ti, int) and raw_ti > 0:
            turn_index = raw_ti

    if producer is None and isinstance(metadata, dict):
        kind_meta = metadata.get("executor_kind") or metadata.get("plugin")
        if isinstance(kind_meta, str) and kind_meta:
            producer = kind_meta
    if producer is None:
        producer = "ageval"

    lines: list[dict[str, Any]] = []
    if include_user:
        lines.append(
            {
                "type": "turn",
                "role": "user",
                "content": prompt,
                "turn_index": turn_index,
                "session_id": session_id,
                "source": "ageval",
            }
        )

    def flush_thought() -> None:
        content = "".join(thought_parts)
        thought_parts.clear()
        timing = dict(thought_timing)
        thought_timing.clear()
        if not content:
            return
        _finalize_timing(timing)
        row: dict[str, Any] = {
            "type": "turn",
            "role": "assistant",
            "part": "thought",
            "content": content,
            "turn_index": turn_index,
            "session_id": session_id,
            "source": producer,
        }
        _copy_timing(row, timing)
        lines.append(_drop_nulls(row, keep={"type", "role", "turn_index", "source"}))

    def flush_assistant_burst() -> None:
        content = "".join(assistant_parts)
        assistant_parts.clear()
        timing = dict(assistant_timing)
        assistant_timing.clear()
        if not content:
            return
        _finalize_timing(timing)
        row: dict[str, Any] = {
            "type": "turn",
            "role": "assistant",
            "content": content,
            "turn_index": turn_index,
            "session_id": session_id,
            "source": producer,
        }
        _copy_timing(row, timing)
        lines.append(_drop_nulls(row, keep={"type", "role", "turn_index", "source"}))

    def flush_tools() -> None:
        for call_id, state in tool_states.items():
            _emit_tool_rows(
                lines,
                call_id=call_id,
                state=state,
                turn_index=turn_index,
                session_id=session_id,
                producer=producer,
            )
        tool_states.clear()

    for ev in events:
        if not isinstance(ev, dict) or ev.get("schema") != EVENT_SCHEMA_VERSION:
            continue
        kind = ev.get("kind")
        if kind == "text":
            text = ev.get("text") if isinstance(ev.get("text"), str) else ""
            channel = ev.get("channel")
            if channel == "thought" and text:
                flush_assistant_burst()
                flush_tools()
                thought_parts.append(text)
                _accumulate_text_timing(thought_timing, ev)
            elif channel == "assistant" and text:
                flush_thought()
                flush_tools()
                assistant_parts.append(text)
                _accumulate_text_timing(assistant_timing, ev)
        elif kind == "tool":
            flush_thought()
            flush_assistant_burst()
            _merge_tool(tool_states, ev)
        elif kind == "permission":
            flush_thought()
            flush_tools()
            permission_events.append(
                {
                    "type": "permission_decision",
                    "outcome": ev.get("outcome"),
                    "option_id": ev.get("option_id"),
                    "policy": ev.get("policy"),
                    "source": producer,
                }
            )
        # kind == opaque: events.jsonl only

    flush_thought()
    flush_tools()
    merged_assistant = (final_text if final_text else "".join(assistant_parts)).strip()
    emitted_tool = any(row.get("type") == "tool_call" for row in lines)
    if merged_assistant or not emitted_tool:
        assistant_line: dict[str, Any] = {
            "type": "turn",
            "role": "assistant",
            "content": merged_assistant,
            "turn_index": turn_index,
            "session_id": session_id,
            "source": producer,
        }
        _finalize_timing(assistant_timing)
        _copy_timing(assistant_line, assistant_timing)
        lines.append(_drop_nulls(assistant_line, keep={"type", "role", "turn_index", "source"}))
    for pe in permission_events:
        pe = {**pe, "turn_index": turn_index, "session_id": session_id}
        lines.append(pe)

    meta_out: dict[str, Any] = {}
    if isinstance(metadata, dict):
        for k, v in metadata.items():
            meta_out[k] = v
    terminal: dict[str, Any] = {
        "type": "terminal",
        "ok": ok,
        "error": error,
        "turn_index": turn_index,
        "session_id": session_id,
        "structured": structured,
        "usage": usage,
        "stop_reason": (metadata or {}).get("stop_reason") if metadata else None,
        "metadata": meta_out,
        "source": "ageval",
    }
    if isinstance(extra, dict) and extra:
        terminal["extra"] = extra
    # Invoke wall-clock lives on metadata.latency_ms; cards read elapsed_ms.
    if terminal.get("elapsed_ms") is None and isinstance(metadata, dict):
        elapsed = _coerce_elapsed_ms(metadata.get("elapsed_ms"))
        if elapsed is None:
            elapsed = _coerce_elapsed_ms(metadata.get("latency_ms"))
        if elapsed is not None:
            terminal["elapsed_ms"] = elapsed
    lines.append(terminal)

    if profile_id:
        for row in lines:
            row["profile_id"] = profile_id
    return lines


def _emit_tool_rows(
    lines: list[dict[str, Any]],
    *,
    call_id: str,
    state: dict[str, Any],
    turn_index: int,
    session_id: str | None,
    producer: str,
) -> None:
    _finalize_tool_state(state)
    tool_line: dict[str, Any] = {
        "type": "tool_call",
        "tool_call_id": call_id,
        "title": state.get("title"),
        "function_name": state.get("function_name") or "tool",
        "kind": state.get("tool_kind"),
        "status": state.get("status"),
        "turn_index": turn_index,
        "session_id": session_id,
        "source": state.get("call_source") or producer,
    }
    args = state.get("args")
    if args is not None:
        tool_line["args"] = args
    _copy_timing(tool_line, state)
    lines.append(_drop_nulls(tool_line, keep={"type", "tool_call_id", "turn_index", "source"}))
    if not _should_emit_observation(state):
        return
    obs: dict[str, Any] = {
        "type": "observation",
        "tool_call_id": call_id,
        "status": state.get("status"),
        "turn_index": turn_index,
        "session_id": session_id,
        "source": state.get("obs_source") or producer,
    }
    if state.get("content") is not None:
        obs["content"] = state["content"]
    if state.get("raw_output") is not None:
        obs["raw_output"] = state["raw_output"]
    _copy_timing(obs, state)
    lines.append(_drop_nulls(obs, keep={"type", "tool_call_id", "turn_index", "source"}))


def _drop_nulls(row: dict[str, Any], *, keep: set[str]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if v is not None or k in keep}


def _merge_tool(tool_states: dict[str, dict[str, Any]], ev: dict[str, Any]) -> None:
    call_id = ev.get("tool_call_id")
    if not isinstance(call_id, str) or not call_id:
        return
    phase = ev.get("phase")
    if phase not in _TOOL_PHASES and phase is not None:
        return

    state = tool_states.setdefault(
        call_id,
        {
            "tool_call_id": call_id,
            "args": {},
            "observation_chunks": [],
        },
    )

    title = ev.get("title")
    if isinstance(title, str) and title:
        prev = state.get("title")
        if not isinstance(prev, str) or len(title) >= len(prev):
            state["title"] = title

    for key, dest in (
        ("function_name", "function_name"),
        ("tool_kind", "tool_kind"),
        ("status", "status"),
    ):
        val = ev.get(key)
        if val is not None:
            state[dest] = val if isinstance(val, str) else str(val)

    if ev.get("args") is not None:
        state["args"] = ev["args"] if isinstance(ev["args"], dict) else {"value": ev["args"]}
        state["args_from_event"] = True

    if ev.get("raw_output") is not None:
        state["raw_output"] = ev["raw_output"]

    src = ev.get("source")
    if isinstance(src, str) and src:
        if phase == "start" or not state.get("call_source"):
            state["call_source"] = src
        if phase == "update":
            state["obs_source"] = src

    content = ev.get("content")
    if isinstance(content, str) and content:
        chunks: list[str] = state.setdefault("observation_chunks", [])
        if not chunks or chunks[-1] != content:
            chunks.append(content)

    _merge_timing(state, ev)


def _finalize_tool_state(state: dict[str, Any]) -> None:
    if not state.get("function_name") or state.get("function_name") == "tool":
        kind = state.get("tool_kind")
        if isinstance(kind, str) and kind and kind != "other":
            state["function_name"] = kind
        else:
            title = state.get("title")
            if isinstance(title, str) and title.strip():
                state["function_name"] = title.strip().splitlines()[0]
            else:
                state["function_name"] = "tool"

    chunks: list[str] = list(state.get("observation_chunks") or [])
    if chunks:
        state["content"] = "\n\n".join(chunks)
    if state.get("args") is None:
        state["args"] = {}
    _finalize_timing(state)


def _should_emit_observation(state: dict[str, Any]) -> bool:
    if state.get("content"):
        return True
    if state.get("raw_output") is not None:
        return True
    status = state.get("status")
    return isinstance(status, str) and status.lower() in {"completed", "failed"}


def _copy_timing(row: dict[str, Any], state: dict[str, Any]) -> None:
    elapsed = _coerce_elapsed_ms(state.get("elapsed_ms"))
    if elapsed is not None and elapsed > 0:
        row["elapsed_ms"] = elapsed
    started = state.get("started_at")
    if isinstance(started, str) and started:
        row["started_at"] = started
    ended = state.get("ended_at")
    if isinstance(ended, str) and ended:
        row["ended_at"] = ended


def _accumulate_text_timing(state: dict[str, Any], ev: dict[str, Any]) -> None:
    """Sum observational LLM/step duration onto the current thought/assistant burst."""
    elapsed = _coerce_elapsed_ms(ev.get("elapsed_ms"))
    if elapsed is not None and elapsed > 0:
        prev = _coerce_elapsed_ms(state.get("elapsed_ms")) or 0.0
        state["elapsed_ms"] = prev + elapsed
    started = _coerce_iso(ev.get("started_at") or ev.get("at"))
    if started is not None and state.get("started_at") is None:
        state["started_at"] = started
    ended = _coerce_iso(ev.get("ended_at") or ev.get("at"))
    if ended is not None:
        state["ended_at"] = ended


def _merge_timing(state: dict[str, Any], ev: dict[str, Any]) -> None:
    elapsed = _coerce_elapsed_ms(ev.get("elapsed_ms"))
    if elapsed is not None:
        state["elapsed_ms"] = elapsed

    started = _coerce_iso(ev.get("started_at"))
    if started is not None and state.get("started_at") is None:
        state["started_at"] = started

    ended = _coerce_iso(ev.get("ended_at"))
    if ended is not None:
        state["ended_at"] = ended
        state["ended_at_explicit"] = True

    at = _coerce_iso(ev.get("at"))
    if at is None:
        return
    if state.get("started_at") is None:
        state["started_at"] = at
    if not state.get("ended_at_explicit"):
        state["ended_at"] = at


def _finalize_timing(state: dict[str, Any]) -> None:
    if state.get("elapsed_ms") is not None:
        return
    started = _parse_iso(state.get("started_at"))
    ended = _parse_iso(state.get("ended_at"))
    if started is None or ended is None:
        return
    delta_ms = (ended - started).total_seconds() * 1000.0
    if delta_ms < 0:
        delta_ms = 0.0
    state["elapsed_ms"] = round(delta_ms, 3)


def _coerce_elapsed_ms(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _coerce_iso(value: Any) -> str | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return _format_iso(parsed)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_iso(value: datetime) -> str:
    utc = value.astimezone(UTC)
    stamp = utc.strftime("%Y-%m-%dT%H:%M:%S")
    micros = utc.microsecond
    if micros:
        stamp = f"{stamp}.{micros:06d}".rstrip("0")
    return stamp + "Z"
