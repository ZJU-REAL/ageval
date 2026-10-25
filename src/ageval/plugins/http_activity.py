"""Strategy A step brackets for single-call HTTP executors."""

from __future__ import annotations

from typing import Any

from ageval.evidence.activity import ActivityScope
from ageval.plugins.agent_result import AgentResult


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


def finish_model_turn(executor: Any, step: int | None, result: AgentResult) -> AgentResult:
    scope = _scope(executor)
    if scope is None or step is None:
        return result
    calls = [dict(item) for item in (result.tool_calls or []) if isinstance(item, dict)]
    if result.ok:
        scope.record_model_turn_completed(
            step,
            assistant_text=result.text or "",
            thought=None,
            tool_calls=calls,
            usage=_usage_dict(result.usage),
            stop_reason="stop",
        )
        return result
    scope.record_model_turn_aborted(
        step,
        partial_text=result.text or "",
        reason=str(result.error or "model_error"),
    )
    return result


def abort_model_turn(executor: Any, step: int | None, *, reason: str) -> None:
    scope = _scope(executor)
    if scope is None or step is None:
        return
    scope.record_model_turn_aborted(step, partial_text="", reason=reason)


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
