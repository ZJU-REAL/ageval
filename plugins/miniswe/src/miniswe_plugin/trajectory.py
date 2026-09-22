"""Map mini-swe-agent messages to ``ageval.trajectory.event/1``.

Shape matches Core fold / Viewer: ``kind: tool`` + ``tool_call_id`` +
``phase: start|update`` (same contract as openai-http). No ACP
``session_update``. Importable without ageval Core.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

SCHEMA = "ageval.trajectory.event/1"
_SOURCE = "miniswe"


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _actions_from_message(raw: dict[str, Any], extra: dict[str, Any]) -> list[dict[str, Any]]:
    actions = extra.get("actions")
    if isinstance(actions, list):
        out = [a for a in actions if isinstance(a, dict)]
        if out:
            return out
    tcs = raw.get("tool_calls")
    if not isinstance(tcs, list):
        return []
    parsed: list[dict[str, Any]] = []
    for tc in tcs:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        args = fn.get("arguments") if isinstance(fn, dict) else None
        cmd = ""
        if isinstance(args, dict):
            cmd = str(args.get("command") or "")
        elif isinstance(args, str) and args.strip():
            try:
                obj = json.loads(args)
            except json.JSONDecodeError:
                cmd = args
            else:
                cmd = str(obj.get("command") or "") if isinstance(obj, dict) else args
        parsed.append(
            {
                "command": cmd,
                "tool_call_id": str(tc.get("id") or ""),
            }
        )
    return parsed


def _thought_text(raw: dict[str, Any]) -> str:
    """OpenAI-compatible thinking text. Not provider-specific."""
    for key in ("reasoning_content", "reasoning"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[-8000:]
    return ""


def _call_id(action: dict[str, Any], *, seq: int, index: int) -> str:
    for key in ("tool_call_id", "id", "call_id"):
        raw = action.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return f"miniswe_{seq}_{index}"


def to_ageval_trajectory_events(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    session_id: str = "miniswe",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seq = 0
    pending: deque[str] = deque()
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "")
        extra = _as_dict(raw.get("extra"))
        rc = extra.get("returncode")
        if role in {"system", "user"} and rc is None:
            seq += 1
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": _SOURCE,
                    "kind": "text",
                    "channel": role,
                    "text": str(raw.get("content") or "")[:8000],
                }
            )
            continue
        if role == "assistant":
            thought = _thought_text(raw)
            if thought:
                seq += 1
                out.append(
                    {
                        "schema": SCHEMA,
                        "seq": seq,
                        "session_id": session_id,
                        "source": _SOURCE,
                        "kind": "text",
                        "channel": "thought",
                        "text": thought,
                    }
                )
            spoken = raw.get("content")
            spoken_text = spoken.strip() if isinstance(spoken, str) else ""
            if spoken_text:
                seq += 1
                out.append(
                    {
                        "schema": SCHEMA,
                        "seq": seq,
                        "session_id": session_id,
                        "source": _SOURCE,
                        "kind": "text",
                        "channel": "assistant",
                        "text": spoken_text[:8000],
                    }
                )
            pending.clear()
            for i, action in enumerate(_actions_from_message(raw, extra)):
                seq += 1
                call_id = _call_id(action, seq=seq, index=i)
                pending.append(call_id)
                cmd = str(action.get("command") or action.get("cmd") or "")
                out.append(
                    {
                        "schema": SCHEMA,
                        "seq": seq,
                        "session_id": session_id,
                        "source": _SOURCE,
                        "kind": "tool",
                        "phase": "start",
                        "tool_call_id": call_id,
                        "function_name": "bash",
                        "title": "bash",
                        "args": {"command": cmd},
                        "status": "pending",
                    }
                )
            continue
        if role in {"tool", "user"} and rc is not None:
            seq += 1
            raw_id = raw.get("tool_call_id")
            if isinstance(raw_id, str) and raw_id.strip():
                call_id = raw_id.strip()
            elif pending:
                call_id = pending.popleft()
            else:
                call_id = f"miniswe_{seq}_obs"
            try:
                code = int(rc)
            except (TypeError, ValueError):
                code = 1
            content = str(
                raw.get("content") or extra.get("output") or extra.get("raw_output") or ""
            )
            raw_output = extra.get("raw_output")
            if raw_output is None:
                raw_output = extra.get("output")
            event: dict[str, Any] = {
                "schema": SCHEMA,
                "seq": seq,
                "session_id": session_id,
                "source": _SOURCE,
                "kind": "tool",
                "phase": "update",
                "tool_call_id": call_id,
                "function_name": "bash",
                "title": "bash",
                "content": content[:8000],
                "status": "completed" if code == 0 else "failed",
            }
            if raw_output is not None:
                event["raw_output"] = raw_output if isinstance(raw_output, str) else str(raw_output)
            out.append(event)
            continue
        if role == "exit":
            seq += 1
            out.append(
                {
                    "schema": SCHEMA,
                    "seq": seq,
                    "session_id": session_id,
                    "source": _SOURCE,
                    "kind": "text",
                    "channel": "exit",
                    "text": str(raw.get("content") or extra.get("exit_status") or ""),
                }
            )
    return out
