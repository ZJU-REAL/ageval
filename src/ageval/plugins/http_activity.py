"""Strategy A step brackets and live fragments for single-call HTTP executors."""

from __future__ import annotations

import threading
import time
from typing import Any

from ageval.evidence.activity import ActivityScope
from ageval.evidence.redaction import IncrementalTextRedactor
from ageval.plugins.agent_result import AgentResult

_DELTA_CHANNELS = frozenset({"assistant", "thought", "tool"})


class DeltaChannelError(ValueError):
    """A live fragment named a channel the activity log does not carry."""

    def __init__(self, channel: str) -> None:
        super().__init__(channel)
        self.channel = channel


_DELTA_CHUNK = 4096
_DELTA_FLUSH_SECONDS = 0.2


def messages_for_turn(
    executor: Any,
    prompt: str,
    messages: Any,
) -> Any:
    """Caller messages win. Otherwise project the session log."""
    if messages:
        return messages
    scope = _scope(executor)
    if scope is None:
        return None
    projected = scope.project_messages()
    return projected or None


def begin_model_turn(executor: Any, prompt: str, messages: Any) -> int | None:
    scope = _scope(executor)
    if scope is None:
        return None
    step = _next_step(scope)
    if messages:
        delta = [dict(item) for item in messages if isinstance(item, dict)]
    else:
        delta = [{"role": "user", "content": prompt}]
    scope.record_model_turn_in_flight(step, delta)
    return step


def finish_model_turn(
    executor: Any,
    step: int | None,
    result: AgentResult,
    *,
    thought: str | None = None,
    stop_reason: str | None = None,
) -> AgentResult:
    scope = _scope(executor)
    if scope is None or step is None:
        return result
    calls = [dict(item) for item in (result.tool_calls or []) if isinstance(item, dict)]
    if result.ok:
        scope.record_model_turn_completed(
            step,
            assistant_text=result.text or "",
            thought=thought or None,
            tool_calls=calls,
            usage=_usage_dict(result.usage),
            stop_reason=stop_reason or "stop",
        )
        return result
    scope.record_model_turn_aborted(
        step,
        partial_text=result.text or "",
        partial_thought=thought or None,
        reason=str(result.error or "model_error"),
    )
    return result


def abort_model_turn(
    executor: Any,
    step: int | None,
    *,
    reason: str,
    partial_text: str = "",
    partial_thought: str | None = None,
) -> None:
    scope = _scope(executor)
    if scope is None or step is None:
        return
    scope.record_model_turn_aborted(
        step,
        partial_text=partial_text,
        partial_thought=partial_thought,
        reason=reason,
    )


class ModelTurnDeltaWriter:
    """Batch live fragments into ``model_turn/delta`` activity rows.

    The final ``finish_model_turn`` call remains the single terminal seal. The
    writer only makes progress visible while the HTTP call is still running.
    """

    def __init__(self, executor: Any, step: int | None) -> None:
        self._executor = executor
        self._step = step
        self._lock = threading.Lock()
        self._pending: dict[tuple[str, int | None, str | None], list[str]] = {}
        self._characters = 0
        self._last_flush = 0.0
        self._redactors: dict[tuple[str, int | None, str | None], IncrementalTextRedactor] = {}

    def append(
        self,
        channel: str,
        text: str,
        *,
        tool_index: int | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        if not text:
            return
        if channel not in _DELTA_CHANNELS:
            raise DeltaChannelError(channel)
        if self._step is None or _scope(self._executor) is None:
            return
        with self._lock:
            key = (channel, tool_index, tool_call_id)
            self._pending.setdefault(key, []).append(text)
            self._characters += len(text)
            due = (
                self._characters >= _DELTA_CHUNK
                or time.monotonic() - self._last_flush >= _DELTA_FLUSH_SECONDS
            )
            if due:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        with self._lock:
            self._flush_locked(final=True)

    def _flush_locked(self, *, final: bool = False) -> None:
        pending = self._pending
        self._pending = {}
        self._characters = 0
        self._last_flush = time.monotonic()
        scope = _scope(self._executor)
        step = self._step
        if scope is None or step is None:
            return
        keys = self._redactors.keys() | pending.keys() if final else pending.keys()
        for channel, tool_index, tool_call_id in keys:
            key = (channel, tool_index, tool_call_id)
            redactor = self._redactors.setdefault(
                key, IncrementalTextRedactor(extra_sentinels=scope.log.sentinels)
            )
            text = redactor.feed("".join(pending.get(key, ())), final=final)
            for start in range(0, len(text), _DELTA_CHUNK):
                scope.record_model_turn_delta(
                    step,
                    channel=channel,
                    text=text[start : start + _DELTA_CHUNK],
                    tool_index=tool_index,
                    tool_call_id=tool_call_id,
                )


def _scope(executor: Any) -> ActivityScope | None:
    scope = getattr(executor, "activity", None)
    if isinstance(scope, ActivityScope):
        return scope
    return None


def _next_step(scope: ActivityScope) -> int:
    best = 0
    for record in scope.log.records:
        if record.kind != "model_turn":
            continue
        if record.payload.get("invoke_request_id") != scope.invoke_request_id:
            continue
        raw = record.payload.get("step_index")
        if isinstance(raw, int) and not isinstance(raw, bool):
            best = max(best, raw)
    return best + 1


def _usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None or isinstance(usage, dict):
        return usage if isinstance(usage, dict) else None
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if prompt is None and completion is None:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens": getattr(usage, "cached_tokens", None),
        "cost_usd": getattr(usage, "cost_usd", None),
    }
