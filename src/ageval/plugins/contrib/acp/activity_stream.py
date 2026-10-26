"""Stream ACP session updates into the attempt activity log."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_REPLAY_SAFE = frozenset({"read", "search", "think", "fetch"})
_DONE = frozenset({"completed", "complete", "done", "ok", "success", "failed", "error"})


@dataclass
class StreamState:
    open_step: int | None = None
    assistant: list[str] = field(default_factory=list)
    thought: list[str] = field(default_factory=list)
    tools: set[str] = field(default_factory=set)
    finished: set[str] = field(default_factory=set)
    step: int = 0


def state_of(client: Any) -> StreamState:
    current = getattr(client, "_activity_state", None)
    if isinstance(current, StreamState):
        return current
    created = StreamState()
    client._activity_state = created
    return created


def prime_stream_state(client: Any, scope: Any) -> StreamState:
    """Continue step numbers and skip tool ids already stored for this invoke."""
    state = StreamState()
    log = getattr(scope, "log", None) if scope is not None else None
    invoke = getattr(scope, "invoke_request_id", None) if scope is not None else None
    if log is not None and isinstance(invoke, str):
        for record in log.records:
            if record.payload.get("invoke_request_id") != invoke:
                continue
            if record.kind == "model_turn":
                raw = record.payload.get("step_index")
                if isinstance(raw, int) and not isinstance(raw, bool):
                    state.step = max(state.step, raw)
            if record.kind != "tool_call":
                continue
            call_id = record.payload.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                continue
            state.tools.add(call_id)
            if record.status in {"completed", "aborted"}:
                state.finished.add(call_id)
    client._activity_state = state
    return state


def note_native_session(scope: Any, native_session_id: str) -> None:
    if scope is None or not native_session_id:
        return
    log = getattr(scope, "log", None)
    session_id = getattr(scope, "session_id", None)
    if log is None or not isinstance(session_id, str):
        return
    log.update_session_native_id(session_id, native_session_id)


def native_session_id(scope: Any) -> str | None:
    if scope is None:
        return None
    log = getattr(scope, "log", None)
    session_id = getattr(scope, "session_id", None)
    if log is None or not isinstance(session_id, str):
        return None
    record = log.session_record(session_id)
    if record is None:
        return None
    raw = record.payload.get("native_session_id")
    return raw if isinstance(raw, str) and raw else None


def apply_update(scope: Any, client: Any, update: Any, event: dict[str, Any]) -> None:
    """Record one ACP update before ``session/prompt`` returns."""
    if scope is None or not hasattr(scope, "record_tool_call_in_flight"):
        return
    state = state_of(client)
    kind = _update_kind(update, event)
    if "compact" in kind:
        _compaction(scope, event)
        return
    if kind in {"tool_call", "toolcall"}:
        _seal_model(scope, state)
        _tool_started(scope, state, update, event)
        return
    if kind in {"tool_call_update", "toolcallupdate"}:
        _tool_finished(scope, state, update, event)
        return
    if kind in {"agent_message_chunk", "agent_message", "agentmessagechunk"}:
        _chunk(scope, state, event, thought=False)
        return
    if kind in {"agent_thought_chunk", "agent_thought", "agentthoughtchunk"}:
        _chunk(scope, state, event, thought=True)


def seal_open_turn(scope: Any, client: Any) -> None:
    if scope is None:
        return
    _seal_model(scope, state_of(client))


def prompt_for_resume(scope: Any, prompt: str, *, resumed_native: bool) -> str:
    """Keep a recovered invoke on the native session, or replay the transcript."""
    if scope is None or not _has_history(scope):
        return prompt
    note = _continuation(scope)
    if resumed_native:
        return f"{note}\n\n{prompt}" if note else prompt
    transcript = _transcript(scope)
    parts = [part for part in (transcript, note, prompt) if part]
    return "\n\n".join(parts)


def _update_kind(update: Any, event: dict[str, Any]) -> str:
    dumped = event.get("update") if isinstance(event.get("update"), dict) else {}
    raw = (
        getattr(update, "session_update", None)
        or dumped.get("sessionUpdate")
        or dumped.get("session_update")
        or event.get("update_type")
        or ""
    )
    return str(raw).replace("-", "_").lower()


def _chunk(scope: Any, state: StreamState, event: dict[str, Any], *, thought: bool) -> None:
    text = event.get("text") if isinstance(event.get("text"), str) else ""
    if state.open_step is None:
        state.step += 1
        state.open_step = state.step
        scope.record_model_turn_in_flight(state.open_step, [])
    if thought:
        state.thought.append(text)
    else:
        state.assistant.append(text)


def _seal_model(scope: Any, state: StreamState) -> None:
    if state.open_step is None:
        return
    thought = "".join(state.thought).strip()
    scope.record_model_turn_completed(
        state.open_step,
        assistant_text="".join(state.assistant),
        thought=thought or None,
        stop_reason="stop",
    )
    state.open_step = None
    state.assistant.clear()
    state.thought.clear()


def _tool_started(scope: Any, state: StreamState, update: Any, event: dict[str, Any]) -> None:
    call_id = _call_id(update, event)
    if not call_id or call_id in state.tools:
        return
    state.tools.add(call_id)
    kind = _tool_kind(update, event)
    arguments = _arguments(update, event)
    command = arguments.get("command") if isinstance(arguments.get("command"), str) else ""
    cwd = arguments.get("cwd") if isinstance(arguments.get("cwd"), str) else None
    from ageval.evidence.system_effect import command_system_effect

    scope.record_tool_call_in_flight(
        call_id,
        _tool_name(update, event),
        kind,
        arguments,
        replay_safe=kind in _REPLAY_SAFE,
        system_effect=kind == "execute" and command_system_effect(command, cwd),
    )


def _tool_finished(scope: Any, state: StreamState, update: Any, event: dict[str, Any]) -> None:
    status = str(_field(update, event, "status") or "").lower()
    if status and status not in _DONE:
        return
    call_id = _call_id(update, event)
    if not call_id or call_id in state.finished:
        return
    state.finished.add(call_id)
    if call_id not in state.tools:
        _tool_started(scope, state, update, event)
    from ageval.plugins.step_activity import checkpoint_prepare

    outcome = "error" if status in {"failed", "error"} else "ok"
    raw = event.get("update") if isinstance(event.get("update"), dict) else {}
    content = raw.get("rawOutput") or raw.get("raw_output") or raw.get("content") or ""
    scope.record_tool_call_completed(
        call_id,
        outcome=outcome,
        exit_code=0 if outcome == "ok" else 1,
        content=content if isinstance(content, str) else str(content),
        prepare=checkpoint_prepare(scope),
    )


def _compaction(scope: Any, event: dict[str, Any]) -> None:
    from ageval.plugins.step_activity import checkpoint_prepare

    dumped = event.get("update") if isinstance(event.get("update"), dict) else {}
    rel = dumped.get("nativeJournalRel") or dumped.get("path") or dumped.get("sessionFile")
    journal = rel if isinstance(rel, str) else None
    if isinstance(journal, str) and journal.startswith("/attempt/home/"):
        journal = journal.removeprefix("/attempt/home/")
    scope.record_compaction(
        source="native_home",
        native_journal_rel=journal,
        prepare=checkpoint_prepare(scope),
    )


def _has_history(scope: Any) -> bool:
    invoke = scope.invoke_request_id
    for record in scope.log.records:
        if record.payload.get("invoke_request_id") != invoke:
            continue
        if record.kind in {"model_turn", "tool_call"} and record.status == "completed":
            return True
    return False


def _transcript(scope: Any) -> str:
    invoke = scope.invoke_request_id
    lines = ["Completed work from the interrupted attempt. Do not repeat it."]
    for record in scope.log.records:
        if record.payload.get("invoke_request_id") != invoke or record.status != "completed":
            continue
        if record.kind == "model_turn":
            text = str(record.payload.get("assistant_text") or "").strip()
            if text:
                lines.append(f"assistant: {text[:500]}")
        elif record.kind == "tool_call":
            call_id = record.payload.get("tool_call_id")
            content = str(record.payload.get("content") or "")[:300]
            lines.append(f"tool {call_id}: {content}")
    return "\n".join(lines)


def _continuation(scope: Any) -> str:
    invoke = scope.invoke_request_id
    for record in reversed(scope.log.records):
        if record.kind != "tool_call" or record.status != "completed":
            continue
        if record.payload.get("invoke_request_id") != invoke:
            continue
        if record.payload.get("outcome") != "interrupted":
            return ""
        call_id = record.payload.get("tool_call_id")
        content = str(record.payload.get("content") or "")[:500]
        return f"Tool {call_id} was interrupted. Partial output:\n{content}"
    return ""


def _call_id(update: Any, event: dict[str, Any]) -> str:
    raw = event.get("tool_call_id") or _field(update, event, "toolCallId")
    return str(raw) if raw else ""


def _tool_name(update: Any, event: dict[str, Any]) -> str:
    raw = event.get("title") or _field(update, event, "title") or "tool"
    return str(raw)


def _tool_kind(update: Any, event: dict[str, Any]) -> str:
    raw = event.get("kind") or _field(update, event, "kind") or "other"
    return str(raw).lower()


def _arguments(update: Any, event: dict[str, Any]) -> dict[str, Any]:
    dumped = event.get("update") if isinstance(event.get("update"), dict) else {}
    raw = dumped.get("rawInput") or dumped.get("raw_input") or dumped.get("arguments") or {}
    return raw if isinstance(raw, dict) else {"value": raw}


def _field(update: Any, event: dict[str, Any], name: str) -> Any:
    if name in event:
        return event[name]
    dumped = event.get("update") if isinstance(event.get("update"), dict) else {}
    if name in dumped:
        return dumped[name]
    return getattr(update, name, None)
