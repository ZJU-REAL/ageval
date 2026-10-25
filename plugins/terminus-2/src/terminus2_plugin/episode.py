"""Host episode: model reply, parse, tmux, capture, repeat."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from terminus2_plugin.parser import ParseResult, parse_response
from terminus2_plugin.prompt import format_repair, system_prompt, user_prompt
from terminus2_plugin.tmux import TmuxSession
from terminus2_plugin.trajectory import episode_events

ModelCall = Callable[[list[dict[str, Any]]], Any]


@dataclass
class EpisodeResult:
    ok: bool
    error: str | None
    text: str
    events: tuple[dict[str, Any], ...]
    usage: dict[str, int]
    raw: dict[str, Any]
    keys_sent: bool = False
    replies: list[str] = field(default_factory=list)


def run_episode(
    *,
    instruction: str,
    session: TmuxSession,
    model: ModelCall,
    parser: str,
    step_limit: int,
    max_format_errors: int,
    timeout: float,
    session_id: str,
    activity: Any = None,
    reuse_session: bool = False,
) -> EpisodeResult:
    """Drive one task. ``step_limit`` of 0 does not cap turns; ``timeout`` still does."""
    session.start(reuse=reuse_session)
    screen = session.capture()
    restored = _restore_episode(activity, parser=parser)
    if restored is None:
        messages = [
            {"role": "system", "content": system_prompt(parser)},
            {"role": "user", "content": user_prompt(instruction, screen)},
        ]
        usage = _blank_usage()
        format_errors = 0
        turns = 0
    else:
        messages, turns, format_errors, usage = restored
        if _restored_complete(messages, parser):
            return _finish(
                ok=True,
                error=None,
                text=_last_assistant(messages) or "task_complete",
                records=[],
                usage=usage,
                replies=[],
                keys_sent=_logged_keys(activity),
                session_id=session_id,
                turns=turns,
            )
    records: list[dict[str, Any]] = []
    replies: list[str] = []
    keys_sent = False
    deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
    final = ""
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return _finish(
                ok=False,
                error="terminus2_timeout",
                text=final,
                records=records,
                usage=usage,
                replies=replies,
                keys_sent=keys_sent,
                session_id=session_id,
                turns=turns,
            )
        if step_limit > 0 and turns >= step_limit:
            return _finish(
                ok=False,
                error="terminus2_step_limit",
                text=final,
                records=records,
                usage=usage,
                replies=replies,
                keys_sent=keys_sent,
                session_id=session_id,
                turns=turns,
            )
        text, reply_usage, step = _model_turn(activity, messages, model)
        turns += 1
        replies.append(text)
        _merge_usage(usage, reply_usage)
        parsed = parse_response(text, parser=parser)
        reason = "format_error" if parsed.error else "stop"
        _seal_model_turn(activity, step, text, reply_usage, reason)
        if parsed.error:
            format_errors += 1
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": format_repair(parsed.error, parser=parser)})
            if format_errors >= max_format_errors:
                return _finish(
                    ok=False,
                    error=f"terminus2_format:{parsed.error}",
                    text=text,
                    records=records,
                    usage=usage,
                    replies=replies,
                    keys_sent=keys_sent,
                    session_id=session_id,
                    turns=turns,
                )
            continue
        format_errors = 0
        final = parsed.analysis or final
        call_id = f"tmux_{turns}"
        _begin_tmux(activity, parsed, call_id)
        session.exec_request_id = _exec_request(activity, call_id)
        try:
            applied = _apply_commands(parsed, session=session, records=records)
        finally:
            session.exec_request_id = None
        if applied:
            keys_sent = True
        if parsed.is_task_complete:
            screen = records[-1].get("screen") if records else ""
            _end_tmux(activity, parsed, records, call_id=call_id, content=str(screen or ""))
            return _finish(
                ok=True,
                error=None,
                text=final or "task_complete",
                records=records,
                usage=usage,
                replies=replies,
                keys_sent=keys_sent,
                session_id=session_id,
                turns=turns,
            )
        screen = session.capture()
        follow = user_prompt(instruction, screen)
        _end_tmux(activity, parsed, records, call_id=call_id, content=follow)
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": follow})


def _model_turn(
    activity: Any,
    messages: list[dict[str, Any]],
    model: ModelCall,
) -> tuple[str, object, int | None]:
    scope = (
        activity
        if activity is not None and hasattr(activity, "record_model_turn_in_flight")
        else None
    )
    if scope is None:
        reply = model(messages)
        text = str(getattr(reply, "text", "") or "")
        return text, getattr(reply, "usage", None), None
    from ageval.plugins.step_activity import next_step

    step = next_step(scope)
    scope.record_model_turn_in_flight(
        step, [dict(item) for item in messages if isinstance(item, dict)]
    )
    try:
        reply = model(messages)
    except Exception:  # noqa: BLE001 — a cut-off model turn stays in the log
        scope.record_model_turn_aborted(step, reason="process_interrupted")
        raise
    text = str(getattr(reply, "text", "") or "")
    return text, getattr(reply, "usage", None), step


def _seal_model_turn(
    activity: Any,
    step: int | None,
    text: str,
    usage: object,
    stop_reason: str,
) -> None:
    if step is None or activity is None or not hasattr(activity, "record_model_turn_completed"):
        return
    activity.record_model_turn_completed(
        step,
        assistant_text=text,
        usage=usage if isinstance(usage, dict) else None,
        stop_reason=stop_reason,
    )


def _restore_episode(
    activity: Any,
    *,
    parser: str,
) -> tuple[list[dict[str, Any]], int, int, dict[str, int]] | None:
    if activity is None or not hasattr(activity, "log"):
        return None
    invoke_id = activity.invoke_request_id
    skip_through, summary = _compaction_floor(activity.log.records, invoke_id)
    messages: list[dict[str, Any]] | None = list(summary) if summary else None
    turns = 0
    format_errors = 0
    usage = _blank_usage()
    for record in activity.log.records:
        if record.seq <= skip_through or record.status != "completed":
            continue
        if record.payload.get("invoke_request_id") != invoke_id:
            continue
        if record.kind == "model_turn":
            inflight = _matching_inflight(activity.log.records, record.request_id)
            if inflight is not None:
                delta = inflight.payload.get("delta_messages")
                if isinstance(delta, list):
                    messages = [dict(item) for item in delta if isinstance(item, dict)]
            if messages is None:
                messages = []
            messages.append(
                {"role": "assistant", "content": str(record.payload.get("assistant_text") or "")}
            )
            turns += 1
            raw_usage = record.payload.get("usage")
            _merge_usage(usage, raw_usage)
            if record.payload.get("stop_reason") == "format_error":
                format_errors += 1
                assistant = str(record.payload.get("assistant_text") or "")
                repair = _format_repair_for(assistant, parser)
                if repair:
                    messages.append({"role": "user", "content": repair})
            else:
                format_errors = 0
        elif record.kind == "tool_call" and messages is not None:
            if _tool_name(activity.log.records, record.request_id) != "tmux":
                continue
            messages.append({"role": "user", "content": str(record.payload.get("content") or "")})
    if messages is None or (not turns and not summary):
        return None
    return messages, turns, format_errors, usage


def _format_repair_for(text: str, parser: str) -> str:
    parsed = parse_response(text, parser=parser)
    if not parsed.error:
        return ""
    return format_repair(parsed.error, parser=parser)


def _compaction_floor(records: list[Any], invoke_id: str) -> tuple[int, list[dict[str, Any]]]:
    skip = 0
    summary: list[dict[str, Any]] = []
    for record in records:
        if record.kind != "compaction" or record.status != "completed":
            continue
        if record.payload.get("invoke_request_id") != invoke_id:
            continue
        raw = record.payload.get("replaces_through_seq")
        if isinstance(raw, int) and not isinstance(raw, bool):
            skip = raw
        packed = record.payload.get("summary_messages")
        if isinstance(packed, list):
            summary = [dict(item) for item in packed if isinstance(item, dict)]
    return skip, summary


def _restored_complete(messages: list[dict[str, Any]], parser: str) -> bool:
    if not messages or messages[-1].get("role") != "assistant":
        return False
    parsed = parse_response(str(messages[-1].get("content") or ""), parser=parser)
    return not parsed.error and parsed.is_task_complete


def _last_assistant(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "assistant":
            return str(item.get("content") or "")
    return ""


def _logged_keys(activity: Any) -> bool:
    if activity is None or not hasattr(activity, "log"):
        return False
    for record in activity.log.records:
        if (
            record.kind == "tool_call"
            and record.status == "completed"
            and _tool_name(activity.log.records, record.request_id) == "tmux"
        ):
            return True
    return False


def _exec_request(activity: Any, call_id: str) -> str | None:
    session_id = getattr(activity, "session_id", None)
    if not isinstance(session_id, str) or not session_id:
        return None
    return f"tool_{session_id}_{call_id}"


def _tool_name(records: list[Any], request_id: str) -> str:
    for record in records:
        if (
            record.kind == "tool_call"
            and record.status == "in_flight"
            and record.request_id == request_id
        ):
            return str(record.payload.get("tool_name") or "")
    return ""


def _matching_inflight(records: list[Any], request_id: str) -> Any:
    for record in records:
        if record.request_id == request_id and record.status == "in_flight":
            return record
    return None


def _apply_commands(
    parsed: ParseResult,
    *,
    session: TmuxSession,
    records: list[dict[str, Any]],
) -> bool:
    sent = False
    for index, command in enumerate(parsed.commands):
        completed, note = session.send(command.keystrokes, command.duration)
        screen = session.capture()
        records.append(
            {
                "analysis": parsed.analysis if index == 0 else "",
                "plan": parsed.plan if index == 0 else "",
                "keystrokes": command.keystrokes,
                "duration": command.duration,
                "completed": completed,
                "note": note,
                "screen": screen,
            }
        )
        sent = True
        if not completed:
            break
    return sent


def _begin_tmux(activity: Any, parsed: ParseResult, call_id: str) -> None:
    if (
        activity is None
        or not parsed.commands
        or not hasattr(activity, "record_tool_call_in_flight")
    ):
        return
    keystrokes = "\n".join(command.keystrokes for command in parsed.commands)
    activity.record_tool_call_in_flight(
        call_id,
        "tmux",
        "execute",
        {"command": keystrokes},
        replay_safe=False,
        timeout_sec=30.0,
    )


def _end_tmux(
    activity: Any,
    parsed: ParseResult,
    records: list[dict[str, Any]],
    *,
    call_id: str,
    content: str,
) -> None:
    if (
        activity is None
        or not parsed.commands
        or not hasattr(activity, "record_tool_call_completed")
    ):
        return
    from ageval.plugins.step_activity import checkpoint_prepare

    ok = bool(records) and bool(records[-1].get("completed"))
    activity.record_tool_call_completed(
        call_id,
        outcome="ok" if ok else "error",
        exit_code=0 if ok else 1,
        content=content,
        prepare=checkpoint_prepare(activity),
    )


def _finish(
    *,
    ok: bool,
    error: str | None,
    text: str,
    records: list[dict[str, Any]],
    usage: dict[str, int],
    replies: list[str],
    keys_sent: bool,
    session_id: str,
    turns: int,
) -> EpisodeResult:
    return EpisodeResult(
        ok=ok,
        error=error,
        text=text,
        events=tuple(episode_events(records, session_id=session_id)),
        usage={key: value for key, value in usage.items() if value},
        raw={"turns": turns, "replies": replies, "steps": records},
        keys_sent=keys_sent,
        replies=replies,
    )


def _blank_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}


def _merge_usage(total: dict[str, int], raw: object) -> None:
    if not isinstance(raw, dict):
        return
    for key in total:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total[key] += value


__all__ = ["EpisodeResult", "run_episode"]
