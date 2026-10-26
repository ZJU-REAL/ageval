"""Map one terminus-2 episode onto ``ageval.trajectory.event/1``."""

from __future__ import annotations

from typing import Any

from terminus2_plugin import PLUGIN_ID

SCHEMA = "ageval.trajectory.event/1"


def episode_events(
    records: list[dict[str, Any]],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """Tool start/update rows for each keystroke batch, plus analysis as thought."""
    out: list[dict[str, Any]] = []
    seq = 0
    for record in records:
        analysis = str(record.get("analysis") or "").strip()
        if analysis:
            seq += 1
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": PLUGIN_ID,
                    "kind": "text",
                    "channel": "thought",
                    "text": analysis[:8000],
                }
            )
        keystrokes = str(record.get("keystrokes") or "")
        if "keystrokes" not in record:
            continue
        seq += 1
        stored = record.get("tool_call_id")
        call_id = stored if isinstance(stored, str) and stored else f"terminus2_{seq}"
        out.append(
            {
                "schema": SCHEMA,
                "seq": seq,
                "session_id": session_id,
                "source": PLUGIN_ID,
                "kind": "tool",
                "phase": "start",
                "tool_call_id": call_id,
                "function_name": "tmux",
                "title": "tmux",
                "args": {"keystrokes": keystrokes[:4000], "duration": record.get("duration")},
                "status": "pending",
            }
        )
        seq += 1
        completed = bool(record.get("completed", True))
        out.append(
            {
                "schema": SCHEMA,
                "seq": seq,
                "session_id": session_id,
                "source": PLUGIN_ID,
                "kind": "tool",
                "phase": "update",
                "tool_call_id": call_id,
                "function_name": "tmux",
                "title": "tmux",
                "content": str(record.get("screen") or "")[:8000],
                "status": "completed" if completed else "failed",
            }
        )
    return out


__all__ = ["SCHEMA", "episode_events"]
