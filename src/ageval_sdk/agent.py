"""AgentSession / Agent thin facade (HC-2).

Logical Attempt-bound session only. Provider continuation remains unsupported.
Real invokes go to parent Agent Service via Unix socket when bound.
The socket wait is asynchronous, so one task's invoke does not block the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


async def _parent_call(payload: dict[str, Any]) -> dict[str, Any]:
    """Length-prefixed JSON over an async Unix socket to parent Agent Service."""
    import json
    import struct

    sock_path = os.environ.get("AGEVAL_AGENT_SERVICE_SOCK")
    if not sock_path:
        return {"ok": False, "error": "agent_session_unbound"}
    if os.environ.get("AGEVAL_OFFLINE_AGENT") == "1" and payload.get("op") == "invoke":
        return {"ok": False, "error": "offline_forced", "structured": None}
    try:
        reader, writer = await asyncio.open_unix_connection(sock_path)
    except OSError as exc:
        return {"ok": False, "error": f"agent_service_connect:{type(exc).__name__}"}
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        writer.write(struct.pack("!I", len(raw)) + raw)
        await writer.drain()
        hdr = await reader.readexactly(4)
        (n,) = struct.unpack("!I", hdr)
        body = await reader.readexactly(n)
        return json.loads(body.decode("utf-8"))
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        return {"ok": False, "error": "agent_service_eof"}
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()


@dataclass
class AgentSession:
    """Attempt-bound logical session (no provider resume token)."""

    attempt_id: str
    profile_id: str
    max_turns: int = 8
    actor_id: str | None = None
    _turns: int = 0
    _closed: bool = False
    provider_session_handle: None = None  # always null/unsupported for Codex
    environment: str | None = None
    _session_id: str | None = field(default=None, repr=False)
    _last_invocation_id: str | None = field(default=None, repr=False)
    _gate: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def _ensure_open(self) -> Mapping[str, Any]:
        if self._session_id is not None:
            return {"ok": True, "session_id": self._session_id}
        payload: dict[str, Any] = {
            "op": "open",
            "attempt_id": self.attempt_id,
            "profile_id": self.profile_id,
        }
        if self.actor_id is not None:
            payload["actor_id"] = self.actor_id
        if self.environment:
            payload["environment"] = self.environment
        resp = await _parent_call(payload)
        if not resp.get("ok"):
            return resp
        self._session_id = str(resp.get("session_id") or "")
        return resp

    async def invoke(self, prompt: str, **kwargs: Any) -> Mapping[str, Any]:
        tools = kwargs.pop("tools", None)
        messages = kwargs.pop("messages", None)
        explicit_request = kwargs.pop("request_id", None)
        if kwargs:
            # Disallow profile/workspace/executor overrides mid-session.
            raise ValueError("session invoke does not accept profile overrides")
        async with self._gate:
            if self._closed:
                raise RuntimeError("session closed")
            if self._turns >= self.max_turns:
                raise RuntimeError("local max_turns exceeded")
            self._turns += 1
            turn = self._turns
            if os.environ.get("AGEVAL_OFFLINE_AGENT") == "1":
                return {
                    "text": "",
                    "structured": None,
                    "provider_session_handle": None,
                    "turn": turn,
                    "ok": False,
                    "error": "offline_forced",
                    "tool_calls": [],
                }
            opened = await self._ensure_open()
            if not opened.get("ok"):
                return {
                    "text": "",
                    "structured": None,
                    "provider_session_handle": None,
                    "turn": turn,
                    "ok": False,
                    "error": opened.get("error") or "agent_session_unbound",
                    "tool_calls": [],
                }
            if isinstance(explicit_request, str) and explicit_request.strip():
                request_id = explicit_request.strip()
            else:
                request_id = f"req_{self._session_id}_turn_{turn}"
            payload: dict[str, Any] = {
                "op": "invoke",
                "session_id": self._session_id,
                "attempt_id": self.attempt_id,
                "prompt": prompt,
                "request_id": request_id,
                "turn_index": turn,
            }
            if tools is not None:
                payload["tools"] = tools
            if messages is not None:
                payload["messages"] = messages
        try:
            resp = await _parent_call(payload)
        except asyncio.CancelledError:
            await asyncio.shield(
                _parent_call(
                    {
                        "op": "cancel",
                        "session_id": self._session_id,
                        "request_id": request_id,
                    }
                )
            )
            raise
        inv = resp.get("invocation_id")
        if isinstance(inv, str) and inv:
            self._last_invocation_id = inv
        return {
            "text": resp.get("text") or "",
            "structured": resp.get("structured"),
            "provider_session_handle": None,
            "turn": turn,
            "ok": bool(resp.get("ok")),
            "error": resp.get("error"),
            "invocation_id": resp.get("invocation_id"),
            "evidence_relative": resp.get("evidence_relative"),
            "tool_calls": list(resp.get("tool_calls") or []),
        }

    async def record_observation(
        self,
        tool_call_id: str,
        *,
        content: str,
        raw_output: Any = None,
        function_name: str | None = None,
        error: bool = False,
        invocation_id: str | None = None,
    ) -> Mapping[str, Any]:
        """Supplement the last invoke with a domain-tool observation.

        Parent does not execute package tools. Call this after ToolSet.call /
        Environment.get_response. Not PASS. Does not consume invoke quota.
        """
        if self._closed:
            raise RuntimeError("session closed")
        if os.environ.get("AGEVAL_OFFLINE_AGENT") == "1":
            return {"ok": False, "error": "offline_forced"}
        if not self._session_id:
            return {"ok": False, "error": "agent_session_unbound"}
        payload: dict[str, Any] = {
            "op": "record_observation",
            "session_id": self._session_id,
            "tool_call_id": tool_call_id,
            "content": content,
            "error": bool(error),
        }
        inv = invocation_id or self._last_invocation_id
        if inv:
            payload["invocation_id"] = inv
        if function_name:
            payload["function_name"] = function_name
        if raw_output is not None:
            payload["raw_output"] = raw_output
        return await _parent_call(payload)

    async def close(self) -> None:
        async with self._gate:
            if self._closed:
                return
            self._closed = True
            session_id = self._session_id
        if session_id:
            await _parent_call({"op": "close", "session_id": session_id})

    async def __aenter__(self) -> AgentSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


@dataclass
class Agent:
    """Thin facade that opens Attempt-bound sessions from context scope."""

    attempt_id: str

    def session(
        self,
        profile_id: str,
        *,
        max_turns: int = 8,
        actor_id: str | None = None,
        environment: str | None = None,
    ) -> AgentSession:
        """Open a logical session.

        L1 packages must pass ``actor_id`` (isolation principal). L0 may omit it.
        ``environment`` names an evaluate-phase scoring host; omit it for the
        singular scoring host. HTTP judges ignore it.
        """
        return AgentSession(
            attempt_id=self.attempt_id,
            profile_id=profile_id,
            max_turns=max_turns,
            actor_id=actor_id,
            environment=environment,
        )
