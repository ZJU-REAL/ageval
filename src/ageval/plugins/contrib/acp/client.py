"""ACP JSON-RPC client helpers and permission auto-approve."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from contextlib import suppress as contextlib_suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ageval.plugins.agent_result import AgentResult
from ageval.plugins.contrib.acp.usage import _as_plain_mapping


def _offline_result(model: str) -> AgentResult:
    return AgentResult(
        model=model,
        text="",
        structured=None,
        ok=False,
        error="offline_forced",
        events=(
            {
                "type": "lifecycle",
                "phase": "skipped",
                "reason": "offline_forced",
                "source": "acp_adapter",
            },
        ),
        metadata={"executor_kind": "acp"},
    )


def _auto_approve_permission(options: Sequence[Any]) -> Any:
    """Batch auto-approve: select first allow-like option (Spec 19 decision 4)."""
    import acp
    from acp.schema import AllowedOutcome

    option_id = None
    for opt in options:
        kind = getattr(opt, "kind", None) or (opt.get("kind") if isinstance(opt, dict) else None)
        oid = getattr(opt, "option_id", None) or (
            opt.get("optionId") if isinstance(opt, dict) else None
        )
        if kind in ("allow_once", "allow_always", "allow", "selected") or (
            isinstance(oid, str) and "allow" in oid.lower()
        ):
            option_id = oid
            break
    if option_id is None and options:
        first = options[0]
        option_id = getattr(first, "option_id", None) or (
            first.get("optionId") if isinstance(first, dict) else None
        )
    if not option_id:
        option_id = "allow"
    return acp.RequestPermissionResponse(
        outcome=AllowedOutcome(option_id=str(option_id), outcome="selected")
    )


@dataclass
class _AgevalAcpClient:
    """Minimal Client: auto-approve permission, decline elicitation, collect updates.

    Usage sources are intentionally split (issue #30):

    * ``latest_usage_update`` — raw ``UsageUpdate`` stream (context used/size + cost)
    * ``prompt_usage`` — set by the executor after ``session/prompt`` returns
      ``PromptResponse.usage`` (token counts)

    Normalized merge lives in :func:`normalize_acp_usage`; do not treat
    ``UsageUpdate.used`` as billable tokens.
    """

    events: list[dict[str, Any]] = field(default_factory=list)
    text_chunks: list[str] = field(default_factory=list)
    latest_usage_update: dict[str, Any] | None = None
    prompt_usage: dict[str, Any] | None = None
    permission_decisions: list[dict[str, Any]] = field(default_factory=list)
    last_activity_monotonic: float = field(default_factory=time.monotonic)
    _conn: Any = None
    activity: Any = None
    suppress_activity: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def mark_activity(self) -> None:
        """Bump the stall clock. Any session/update, permission, or elicitation."""
        self.last_activity_monotonic = time.monotonic()

    def on_connect(self, conn: Any) -> None:
        self._conn = conn

    async def request_permission(
        self,
        session_id: str,
        tool_call: Any,
        options: list[Any],
        **kwargs: Any,
    ) -> Any:
        self.mark_activity()
        resp = _auto_approve_permission(options)
        decision = {
            "type": "permission_decision",
            "session_id": session_id,
            "outcome": "selected",
            "policy": "batch_auto_approve",
            "source": "acp_client",
        }
        # Record option id without tool payloads that may carry paths/secrets.
        try:
            decision["option_id"] = resp.outcome.option_id  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            decision["option_id"] = "allow"
        self.permission_decisions.append(decision)
        self.record(decision)
        return resp

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        """Record full ACP stream for trajectory.jsonl (training-grade).

        ``load_session`` replays history through this callback. Those updates
        are already in the activity log, so ``suppress_activity`` drops them.
        Intermediate AgentMessageChunk / thought text is preserved on the event
        payload (not only text_len).
        """
        if self.suppress_activity:
            return
        self.mark_activity()
        update_type = type(update).__name__
        event: dict[str, Any] = {
            "type": "session_update",
            "session_id": session_id,
            "update_type": update_type,
            "source": "acp",
        }
        # Prefer typed dump when available (full structured update).
        with contextlib_suppress(TypeError, ValueError, AttributeError):
            if hasattr(update, "model_dump"):
                dumped = update.model_dump(by_alias=True, exclude_none=True)
                if isinstance(dumped, dict):
                    event["update"] = dumped

        content = getattr(update, "content", None)
        text = getattr(content, "text", None) if content is not None else None
        is_agent_msg = "AgentMessage" in update_type or update_type.endswith("AgentMessageChunk")
        is_thought = "Thought" in update_type or update_type.endswith("AgentThoughtChunk")
        if isinstance(text, str):
            event["text"] = text
            event["text_len"] = len(text)
            if is_agent_msg:
                self.text_chunks.append(text)
            if is_thought:
                event["channel"] = "thought"
            elif is_agent_msg:
                event["channel"] = "assistant"
        # Tool call updates: keep id/title/kind when present.
        for attr in ("tool_call_id", "toolCallId", "title", "kind", "status"):
            val = getattr(update, attr, None)
            if val is not None and attr not in event:
                # normalize camelCase keys already in model_dump; keep flat helpers
                key = "tool_call_id" if attr in {"tool_call_id", "toolCallId"} else attr
                event[key] = val if not hasattr(val, "value") else str(val)
        # UsageUpdate (context occupancy + cost) — not PromptResponse token Usage.
        dumped_raw = event.get("update")
        dumped_update: dict[str, Any] = dumped_raw if isinstance(dumped_raw, dict) else {}
        session_upd = (
            getattr(update, "session_update", None)
            or dumped_update.get("sessionUpdate")
            or dumped_update.get("session_update")
        )
        is_usage_update = (
            update_type in {"UsageUpdate", "_UsageUpdate"}
            or "UsageUpdate" in update_type
            or (isinstance(session_upd, str) and session_upd.lower() == "usage_update")
        )
        if is_usage_update:
            raw_update = _as_plain_mapping(update)
            if raw_update is None and isinstance(event.get("update"), dict):
                raw_update = dict(event["update"])
            if raw_update is not None:
                self.latest_usage_update = raw_update
                event["usage_update"] = raw_update
                # Keep legacy key for older event consumers (raw UsageUpdate shape).
                event["usage"] = raw_update
            event["has_usage_update"] = True
        self.record(event)
        if self.activity is not None:
            from ageval.plugins.contrib.acp.activity_stream import apply_update

            apply_update(self.activity, self, update, event)

    async def write_text_file(
        self, session_id: str, path: str, content: str, **kwargs: Any
    ) -> None:
        # Not advertised; if called, refuse — tools run in entry process.
        raise RuntimeError("acp_client_fs_proxy_disabled")

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Any:
        raise RuntimeError("acp_client_fs_proxy_disabled")

    async def create_terminal(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("acp_client_terminal_proxy_disabled")

    async def terminal_output(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("acp_client_terminal_proxy_disabled")

    async def release_terminal(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def wait_for_terminal_exit(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("acp_client_terminal_proxy_disabled")

    async def kill_terminal(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def create_elicitation(self, message: str, mode: Any, **kwargs: Any) -> Any:
        import acp

        self.mark_activity()
        self.record(
            {
                "type": "elicitation",
                "action": "decline",
                "policy": "batch_decline",
                "source": "acp_client",
            }
        )
        return acp.DeclineElicitationResponse(action="decline")

    async def complete_elicitation(self, elicitation_id: str, **kwargs: Any) -> None:
        return None

    def snapshot_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self.events)

    def record(self, event: dict[str, Any]) -> None:
        """Append a vendor event and stamp receive-time ``at`` when missing."""
        if "at" not in event:
            event["at"] = _utc_now_iso()
        with self._lock:
            self.events.append(event)

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        return None


def _utc_now_iso() -> str:
    now = datetime.now(UTC)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    if now.microsecond:
        stamp = f"{stamp}.{now.microsecond:06d}".rstrip("0")
    return stamp + "Z"


def _map_stop_reason(stop: str | None) -> tuple[bool, str | None]:
    if stop is None or stop in ("end_turn", "end-turn", "stop"):
        return True, None
    mapping = {
        "max_tokens": "acp_stop_max_tokens",
        "max_turn_requests": "acp_stop_max_turn_requests",
        "refusal": "acp_stop_refusal",
        "cancelled": "acp_cancelled",
        "canceled": "acp_cancelled",
    }
    err = mapping.get(str(stop), f"acp_stop_{stop}")
    return False, err
