"""Map an OpenHands trajectory file to ``ageval.trajectory.event/1``.

The worker writes ``openhands.trajectory/1`` steps. This module does not
import the OpenHands SDK and does not emit ACP ``session_update`` rows.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA = "ageval.trajectory.event/1"
TRAJECTORY_SCHEMA = "openhands.trajectory/1"
_SOURCE = "openhands"
_CLIP = 8_000


def _clip(text: str) -> str:
    return text[:_CLIP]


def _call_id(raw: dict[str, Any], *, seq: int) -> str:
    found = raw.get("tool_call_id")
    if isinstance(found, str) and found.strip():
        return found.strip()
    return f"openhands_{seq}"


def _args(raw: dict[str, Any]) -> dict[str, Any]:
    arguments = raw.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"value": arguments}
        if isinstance(parsed, dict):
            return parsed
    return {}


def to_ageval_trajectory_events(
    steps: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    session_id: str = "openhands",
) -> list[dict[str, Any]]:
    """Translate worker steps into the Core trajectory contract."""
    out: list[dict[str, Any]] = []
    seq = 0
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "")
        if kind == "user_message":
            seq += 1
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": _SOURCE,
                    "kind": "text",
                    "channel": "user",
                    "text": _clip(str(raw.get("content") or "")),
                }
            )
            continue
        if kind == "thought":
            text = str(raw.get("content") or "").strip()
            if text:
                seq += 1
                out.append(
                    {
                        "schema": SCHEMA,
                        "seq": seq,
                        "session_id": session_id,
                        "source": _SOURCE,
                        "kind": "text",
                        "channel": "thought",
                        "text": _clip(text),
                    }
                )
            continue
        if kind == "assistant_message":
            text = str(raw.get("content") or "").strip()
            if text:
                seq += 1
                out.append(
                    {
                        "schema": SCHEMA,
                        "seq": seq,
                        "session_id": session_id,
                        "source": _SOURCE,
                        "kind": "text",
                        "channel": "assistant",
                        "text": _clip(text),
                    }
                )
            continue
        if kind == "tool_call":
            seq += 1
            name = str(raw.get("name") or "tool")
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": _SOURCE,
                    "kind": "tool",
                    "phase": "start",
                    "tool_call_id": _call_id(raw, seq=seq),
                    "function_name": name,
                    "title": name,
                    "args": _args(raw),
                    "status": "pending",
                }
            )
            continue
        if kind == "tool_result":
            seq += 1
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": _SOURCE,
                    "kind": "tool",
                    "phase": "update",
                    "tool_call_id": _call_id(raw, seq=seq),
                    "function_name": str(raw.get("name") or "tool"),
                    "title": str(raw.get("name") or "tool"),
                    "content": _clip(str(raw.get("content") or "")),
                    "status": "completed",
                }
            )
    return out


__all__ = ["SCHEMA", "TRAJECTORY_SCHEMA", "to_ageval_trajectory_events"]
