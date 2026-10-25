"""Read worker step lines from the attempt box while ``exec`` is still running."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ageval.environments.protocol import EnvironmentFailure

STEP_REL = Path(".ageval-state") / "steps.jsonl"
_REMOTE_STEPS = "/attempt/.ageval-state/steps.jsonl"
_REPLAY_SAFE = frozenset({"read", "search", "think", "fetch"})


def step_log(host: Any) -> Path | None:
    """Local steps file. Bind-mounted hosts use ``root``; others use ``step_mirror``."""
    root = getattr(host, "root", None)
    if isinstance(root, Path):
        return root / STEP_REL
    mirror = getattr(host, "step_mirror", None)
    if isinstance(mirror, Path):
        return mirror
    return None


def resume_prefix(scope: Any) -> str:
    """Tell a restarted worker which steps already finished."""
    if scope is None or not hasattr(scope, "log"):
        return ""
    invoke = scope.invoke_request_id
    lines: list[str] = []
    for record in scope.log.records:
        if record.payload.get("invoke_request_id") != invoke or record.status != "completed":
            continue
        if record.kind != "tool_call":
            continue
        call_id = record.payload.get("tool_call_id")
        outcome = record.payload.get("outcome")
        lines.append(f"- {call_id} ({outcome})")
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"These tool calls already finished. Do not run them again.\n{body}\n\n"


async def exec_with_steps(host: Any, argv: list[str], scope: Any, **kwargs: Any) -> Any:
    """Run ``host.exec`` and fold new step lines into the activity log as they appear."""
    path = step_log(host)
    remote: Path | None = None
    if path is None and callable(getattr(host, "download", None)):
        descriptor, name = tempfile.mkstemp(prefix="ageval-steps-")
        os.close(descriptor)
        remote = Path(name)
        path = remote
    cursor = path.stat().st_size if path is not None and path.is_file() else 0
    task = asyncio.create_task(host.exec(argv, **kwargs))
    try:
        while not task.done():
            if remote is not None:
                await _pull_remote_steps(host, remote)
            cursor = drain_steps(path, scope, cursor)
            await asyncio.sleep(0.05)
        return await task
    finally:
        if remote is not None:
            await _pull_remote_steps(host, remote)
        drain_steps(path, scope, cursor)
        if remote is not None:
            remote.unlink(missing_ok=True)


async def _pull_remote_steps(host: Any, dest: Path) -> None:
    """Copy the in-sandbox step log. A missing file is not a failed exec."""
    download = getattr(host, "download", None)
    if not callable(download):
        return
    try:
        await download(_REMOTE_STEPS, dest)
    except (OSError, EnvironmentFailure):
        return


def drain_steps(path: Path | None, scope: Any, cursor: int) -> int:
    if path is None or scope is None or not path.is_file():
        return cursor
    raw = path.read_bytes()
    if cursor > len(raw):
        cursor = 0
    chunk = raw[cursor:]
    if not chunk:
        return cursor
    text = chunk.decode("utf-8", errors="replace")
    consumed = cursor
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            break
        consumed += len(line.encode("utf-8"))
        _apply_line(scope, line.strip())
    return consumed


def _apply_line(scope: Any, line: str) -> None:
    if not line or not hasattr(scope, "record_tool_call_in_flight"):
        return
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(row, dict):
        return
    kind = str(row.get("type") or "")
    if kind == "native_session":
        native = row.get("id")
        if isinstance(native, str) and native:
            from ageval.plugins.contrib.acp.activity_stream import note_native_session

            note_native_session(scope, native)
        return
    if kind == "assistant":
        _model(scope, str(row.get("content") or ""), thought=False)
        return
    if kind == "thought":
        _model(scope, str(row.get("content") or ""), thought=True)
        return
    if kind == "tool_call":
        _tool_started(scope, row)
        return
    if kind == "tool_result":
        _tool_finished(scope, row)


def _model(scope: Any, text: str, *, thought: bool) -> None:
    from ageval.plugins.step_activity import next_step

    step = next_step(scope)
    scope.record_model_turn_in_flight(step, [])
    scope.record_model_turn_completed(
        step,
        assistant_text="" if thought else text,
        thought=text if thought else None,
        stop_reason="stop",
    )


def _known_tool(scope: Any, call_id: str) -> str | None:
    request = f"tool_{scope.session_id}_{call_id}"
    latest = None
    for record in scope.log.records:
        if record.kind == "tool_call" and record.request_id == request:
            latest = record.status
    return latest


def _tool_started(scope: Any, row: dict[str, Any]) -> None:
    call_id = str(row.get("tool_call_id") or "")
    if not call_id or _known_tool(scope, call_id) is not None:
        return
    kind = str(row.get("tool_kind") or "other")
    arguments = row.get("arguments") if isinstance(row.get("arguments"), dict) else {}
    scope.record_tool_call_in_flight(
        call_id,
        str(row.get("name") or "tool"),
        kind,
        arguments,
        replay_safe=kind in _REPLAY_SAFE or row.get("replay_safe") is True,
    )


def _tool_finished(scope: Any, row: dict[str, Any]) -> None:
    call_id = str(row.get("tool_call_id") or "")
    if not call_id or _known_tool(scope, call_id) == "completed":
        return
    if _known_tool(scope, call_id) is None:
        _tool_started(scope, row)
    from ageval.plugins.step_activity import checkpoint_prepare

    outcome = str(row.get("outcome") or "ok")
    scope.record_tool_call_completed(
        call_id,
        outcome=outcome,
        exit_code=0 if outcome == "ok" else 1,
        content=str(row.get("content") or ""),
        prepare=checkpoint_prepare(scope),
    )
