"""Stable Agent outlet contract shared by ACP and openai-http executors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ageval.model.errors import (
    FATAL_INVOKE_KINDS,
    fatal_invoke_detail,
    typed_fatal_failure,
)
from ageval.model.usage import (
    NOT_REPORTED,
    Usage,
    UsageUnavailable,
    adopt_usage,
    is_measured_usage,
)

RESULT_HEALTH_NOOP_TURN: str = "noop_turn"


def fatal_failure_from_worker(
    payload: object,
) -> tuple[BaseException | None, str | None]:
    """Decode one worker's bounded ``fatal_invoke`` marker.

    Workers serialize only the stable kind and an already-bounded detail.
    Container executors turn that back into a typed failure before the parent
    decides whether the invoke is a capability result.
    """
    if not isinstance(payload, Mapping):
        return None, None
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in FATAL_INVOKE_KINDS:
        return None, None
    raw_detail = payload.get("detail")
    detail = raw_detail.strip() if isinstance(raw_detail, str) else ""
    detail = detail or kind
    return (
        typed_fatal_failure(kind, detail),
        fatal_invoke_detail(kind, error=detail),
    )


@dataclass(frozen=True, slots=True)
class AgentResult:
    model: str
    text: str
    structured: dict[str, object] | None
    ok: bool
    error: str | None = None
    stderr: str = ""
    events: tuple[dict[str, Any], ...] = ()
    source_refs: tuple[dict[str, str], ...] = ()
    usage: Usage | UsageUnavailable = NOT_REPORTED
    extra: dict[str, Any] | None = None
    # ACP / executor metadata (lock-safe, no secrets).
    metadata: dict[str, Any] | None = None
    # Native tool channel (openai-http / anthropic-http). Empty when text-only.
    tool_calls: tuple[dict[str, Any], ...] = ()
    # False when this prompt must not be sent again (the workspace already changed).
    repeatable: bool = True
    # The parent stall retries only when this is a TransportStall and repeatable.
    failure: BaseException | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.usage, Usage | UsageUnavailable):
            object.__setattr__(self, "usage", adopt_usage(self.usage))


class AgentExecutor(Protocol):
    kind: str

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> AgentResult: ...


def parse_validated_text_structured(text: str) -> dict[str, object] | None:
    """Return structured only when trimmed final text is a complete JSON object.

    No substring/reverse-scan/regex salvage (Spec 19 decision 5).
    """
    import json

    trimmed = text.strip()
    if not trimmed or not trimmed.startswith("{") or not trimmed.endswith("}"):
        return None
    try:
        val = json.loads(trimmed)
    except json.JSONDecodeError:
        return None
    if isinstance(val, dict):
        return val  # type: ignore[return-value]
    return None


def _is_tool_event(event: Mapping[str, Any]) -> bool:
    if event.get("kind") == "tool":
        return True
    return event.get("type") in {"tool", "tool_call", "tool_call_update"}


def observational_result_health(
    *,
    ok: bool,
    usage: Any,
    actual_model: Any,
    events: Sequence[Mapping[str, Any]] | None,
    extra: Mapping[str, Any] | None = None,
) -> str | None:
    """Flag banner-only ok turns. Observational — never a PASS source."""
    if not ok or is_measured_usage(usage) or extra is not None or actual_model is not None:
        return None
    for event in events or ():
        if isinstance(event, Mapping) and _is_tool_event(event):
            return None
    return RESULT_HEALTH_NOOP_TURN
