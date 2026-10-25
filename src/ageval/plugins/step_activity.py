"""Replay completed executor steps from ``activity.jsonl``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ageval.evidence.activity import ActivityRecord, ActivityScope


def scope_of(executor: Any) -> ActivityScope | None:
    scope = getattr(executor, "activity", None)
    return scope if isinstance(scope, ActivityScope) else None


def next_step(scope: ActivityScope) -> int:
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


def checkpoint_prepare(scope: ActivityScope) -> Callable[[int], dict[str, Any]]:
    capture = getattr(scope, "capture", None)

    def prepare(seq: int) -> dict[str, Any]:
        if not callable(capture):
            return {}
        return {"checkpoint_seq": capture(seq)}

    return prepare


class StepReplay:
    """Completed model turns and tool calls for one invoke, in log order."""

    def __init__(self, scope: ActivityScope, *, tool_names: frozenset[str]) -> None:
        self.models: list[ActivityRecord] = []
        self.tools: list[ActivityRecord] = []
        names = {
            record.request_id: record.payload.get("tool_name")
            for record in scope.log.records
            if record.kind == "tool_call" and record.status == "in_flight"
        }
        for record in scope.log.records:
            if record.status != "completed":
                continue
            if record.payload.get("invoke_request_id") != scope.invoke_request_id:
                continue
            if record.kind == "model_turn":
                self.models.append(record)
            elif record.kind == "tool_call" and names.get(record.request_id) in tool_names:
                self.tools.append(record)

    def take_model(self) -> ActivityRecord | None:
        if not self.models:
            return None
        return self.models.pop(0)

    def take_tool(self) -> ActivityRecord | None:
        if not self.tools:
            return None
        return self.tools.pop(0)
