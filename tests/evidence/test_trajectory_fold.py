"""Neutral trajectory fold: Core writer + ACP mapper (no ACP-shaped events)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ageval.evidence.schema import EVENT_SCHEMA_VERSION
from ageval.evidence.trajectory import (
    turn_rows,
    write_attempt_trajectory,
    write_evaluation_observation,
)
from ageval.plugins.contrib.acp.trajectory_map import acp_session_events_to_ageval


def _read_lines(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write(
    tmp: Path,
    events: Any,
    *,
    prompt: str = "p",
    final_text: str = "",
    structured: dict[str, object] | None = None,
    usage: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    ok: bool = True,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    redaction_sentinels: list[str] | None = None,
) -> Path:
    """Fold one turn and write it the way the record phase does."""
    rows = turn_rows(
        prompt=prompt,
        events=events,
        final_text=final_text,
        structured=structured,
        usage=usage,
        extra=extra,
        ok=ok,
        error=error,
        metadata=metadata,
    )
    return write_attempt_trajectory(
        tmp / "inv",
        [rows],
        redaction_sentinels=redaction_sentinels,
    )


def test_writer_ignores_non_contract_events(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        events=(
            {"type": "session_update", "sessionUpdate": "tool_call", "toolCallId": "x"},
            {
                "schema": EVENT_SCHEMA_VERSION,
                "seq": 1,
                "source": "acp",
                "kind": "text",
                "channel": "assistant",
                "text": "hi",
            },
        ),
        prompt="hello",
        final_text="hi",
        usage={"input_tokens": 1},
        metadata={"executor_kind": "acp", "turn_index": 1},
    )
    lines = _read_lines(path)
    types = [x["type"] for x in lines]
    assert types == ["turn", "turn", "terminal"]
    assert "tool_call" not in types
    assert "acp_session_id" not in lines[0]
    assert lines[1]["source"] == "acp"
    assert lines[0]["source"] == "ageval"


def test_no_tool_events_unchanged_shape(tmp_path: Path) -> None:
    mapped = acp_session_events_to_ageval(
        (
            {
                "type": "session_update",
                "session_id": "s1",
                "channel": "assistant",
                "text": "hi ",
            },
            {
                "type": "session_update",
                "session_id": "s1",
                "channel": "assistant",
                "text": "there",
            },
        )
    )
    path = _write(
        tmp_path,
        events=mapped,
        prompt="hello",
        final_text="hi there",
        usage={"input_tokens": 1},
        metadata={"executor_kind": "acp", "turn_index": 1},
    )
    lines = _read_lines(path)
    types = [x["type"] for x in lines]
    assert types == ["turn", "turn", "terminal"]
    assert lines[0]["role"] == "user"
    assert lines[1]["role"] == "assistant"
    assert lines[1]["content"] == "hi there"
    assert lines[1]["session_id"] == "s1"
    assert "tool_call" not in types


def test_tool_call_and_update_merged(tmp_path: Path) -> None:
    events = (
        {
            "type": "session_update",
            "session_id": "sess_1",
            "update_type": "ToolCall",
            "tool_call_id": "call_001",
            "title": "Reading configuration file",
            "kind": "read",
            "status": "pending",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_001",
                "title": "Reading configuration file",
                "kind": "read",
                "status": "pending",
                "rawInput": {"path": "/workspace/config.json"},
            },
        },
        {
            "type": "session_update",
            "session_id": "sess_1",
            "update_type": "ToolCallUpdate",
            "tool_call_id": "call_001",
            "status": "in_progress",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_001",
                "status": "in_progress",
                "content": [
                    {
                        "type": "content",
                        "content": {"type": "text", "text": "Found 3 configuration files..."},
                    }
                ],
            },
        },
        {
            "type": "session_update",
            "session_id": "sess_1",
            "update_type": "ToolCallUpdate",
            "tool_call_id": "call_001",
            "status": "completed",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_001",
                "status": "completed",
                "content": [
                    {
                        "type": "content",
                        "content": {"type": "text", "text": "Analysis complete. Found 3 issues."},
                    }
                ],
                "rawOutput": {"ok": True, "count": 3},
            },
        },
        {
            "type": "session_update",
            "session_id": "sess_1",
            "channel": "assistant",
            "text": "Done.",
        },
    )
    path = _write(
        tmp_path,
        events=acp_session_events_to_ageval(events),
        prompt="inspect config",
        final_text="Done.",
        metadata={"executor_kind": "acp", "acp_entry_id": "pi", "turn_index": 2},
    )
    lines = _read_lines(path)
    types = [x["type"] for x in lines]
    assert types == ["turn", "tool_call", "observation", "turn", "terminal"]

    tool = lines[1]
    assert tool["tool_call_id"] == "call_001"
    assert tool["kind"] == "read"
    assert tool["status"] == "completed"
    assert tool["args"] == {"path": "/workspace/config.json"}
    assert tool["title"] == "Reading configuration file"
    assert tool["function_name"] == "read"
    assert tool["turn_index"] == 2
    assert tool["session_id"] == "sess_1"
    assert tool["source"] == "acp"
    assert "acp_session_id" not in tool

    obs = lines[2]
    assert obs["type"] == "observation"
    assert obs["tool_call_id"] == "call_001"
    assert obs["status"] == "completed"
    assert "Analysis complete" in (obs.get("content") or "")
    assert obs["raw_output"] == {"ok": True, "count": 3}


def test_multiple_tool_calls_order_preserved(tmp_path: Path) -> None:
    events = (
        {
            "type": "session_update",
            "session_id": "s",
            "tool_call_id": "a",
            "title": "list",
            "kind": "search",
            "status": "completed",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "a",
                "title": "list",
                "kind": "search",
                "status": "completed",
                "rawInput": {"q": "x"},
                "content": [{"type": "content", "content": {"type": "text", "text": "a-out"}}],
            },
        },
        {
            "type": "session_update",
            "session_id": "s",
            "tool_call_id": "b",
            "title": "run",
            "kind": "execute",
            "status": "completed",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "b",
                "title": "run",
                "kind": "execute",
                "status": "completed",
                "rawInput": {"cmd": "ls"},
                "rawOutput": {"stdout": "ok"},
            },
        },
    )
    path = _write(tmp_path, events=acp_session_events_to_ageval(events), prompt="p")
    lines = _read_lines(path)
    tool_ids = [x["tool_call_id"] for x in lines if x["type"] == "tool_call"]
    assert tool_ids == ["a", "b"]


def test_tool_args_redacted(tmp_path: Path) -> None:
    sentinel = "TRAJ_TOOL_SECRET_9f3a"
    events = (
        {
            "type": "session_update",
            "session_id": "s",
            "tool_call_id": "c1",
            "title": "fetch",
            "kind": "fetch",
            "status": "completed",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "c1",
                "title": "fetch",
                "kind": "fetch",
                "status": "completed",
                "rawInput": {"Authorization": f"Bearer {sentinel}", "token": sentinel},
                "rawOutput": {"body": f"cookie={sentinel}"},
            },
        },
    )
    path = _write(
        tmp_path,
        events=acp_session_events_to_ageval(events),
        prompt=f"use {sentinel}",
        final_text="ok",
        redaction_sentinels=[sentinel],
    )
    blob = path.read_text(encoding="utf-8")
    assert sentinel not in blob
    assert "REDACTED" in blob


def test_terminal_meta_stdout_and_title_command(tmp_path: Path) -> None:
    """Pi/ACP path: command in title stream; stdout in update._meta.terminal_output."""
    events = (
        {
            "type": "session_update",
            "session_id": "s",
            "update_type": "ToolCallStart",
            "tool_call_id": "call_term",
            "title": "bash",
            "kind": "execute",
            "status": "pending",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_term",
                "title": "bash",
                "kind": "execute",
                "status": "pending",
                "content": [{"type": "terminal", "terminalId": "call_term"}],
            },
        },
        {
            "type": "session_update",
            "session_id": "s",
            "update_type": "ToolCallProgress",
            "tool_call_id": "call_term",
            "title": "ls -la /attempt/workspace/",
            "kind": "execute",
            "status": "pending",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_term",
                "title": "ls -la /attempt/workspace/",
                "kind": "execute",
                "status": "pending",
            },
        },
        {
            "type": "session_update",
            "session_id": "s",
            "update_type": "ToolCallProgress",
            "tool_call_id": "call_term",
            "status": "in_progress",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_term",
                "status": "in_progress",
                "_meta": {
                    "terminal_output": {
                        "data": "total 20\ndrwxr-xr-x 6 actor instruction.md\n",
                        "terminal_id": "call_term",
                    }
                },
            },
        },
        {
            "type": "session_update",
            "session_id": "s",
            "update_type": "ToolCallProgress",
            "tool_call_id": "call_term",
            "status": "completed",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_term",
                "status": "completed",
                "_meta": {"terminal_exit": {"exit_code": 0}},
            },
        },
    )
    path = _write(
        tmp_path,
        events=acp_session_events_to_ageval(events),
        prompt="list dir",
        final_text="done",
    )
    lines = _read_lines(path)
    tool = next(x for x in lines if x["type"] == "tool_call")
    obs = next(x for x in lines if x["type"] == "observation")
    assert tool["args"] == {"command": "ls -la /attempt/workspace/"}
    assert tool["title"] == "ls -la /attempt/workspace/"
    assert tool["function_name"] == "execute"
    assert "total 20" in (obs.get("content") or "")
    assert "instruction.md" in (obs.get("content") or "")
    assert "[terminal" not in (obs.get("content") or "")


def test_permission_decision_still_emitted(tmp_path: Path) -> None:
    events = (
        {
            "type": "permission_decision",
            "outcome": "selected",
            "option_id": "allow-once",
            "policy": "batch_auto_approve",
            "source": "acp_client",
        },
    )
    path = _write(tmp_path, events=acp_session_events_to_ageval(events), prompt="p")
    lines = _read_lines(path)
    types = [x["type"] for x in lines]
    assert "permission_decision" in types
    pe = next(x for x in lines if x["type"] == "permission_decision")
    assert pe["option_id"] == "allow-once"
    assert pe["source"] == "acp"


def test_opaque_not_folded(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "nooa",
            "kind": "opaque",
            "payload": {"event_type": "BeforeTurn"},
        },
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 2,
            "source": "nooa",
            "kind": "text",
            "channel": "assistant",
            "text": "ok",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="ok")
    lines = _read_lines(path)
    assert [x["type"] for x in lines] == ["turn", "turn", "terminal"]
    assert lines[1]["source"] == "nooa"


def test_writer_copies_elapsed_ms_onto_tool_and_observation(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "acp",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "title": "ls",
            "function_name": "execute",
            "tool_kind": "execute",
            "status": "pending",
            "args": {"command": "ls"},
            "started_at": "2026-08-14T12:00:00Z",
        },
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 2,
            "source": "acp",
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "c1",
            "status": "completed",
            "content": "ok",
            "elapsed_ms": 1420.5,
            "ended_at": "2026-08-14T12:00:01.420Z",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    lines = _read_lines(path)
    tool = next(x for x in lines if x["type"] == "tool_call")
    obs = next(x for x in lines if x["type"] == "observation")
    assert tool["elapsed_ms"] == 1420.5
    assert tool["started_at"] == "2026-08-14T12:00:00Z"
    assert tool["ended_at"] == "2026-08-14T12:00:01.42Z"
    assert obs["elapsed_ms"] == 1420.5
    assert obs["started_at"] == tool["started_at"]
    # Tool events do not stamp the terminal row; invoke latency is a separate copy.
    assert "elapsed_ms" not in next(x for x in lines if x["type"] == "terminal")


def test_writer_derives_elapsed_ms_from_started_and_ended(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "acp",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "function_name": "read",
            "at": "2026-08-14T12:00:00.000Z",
        },
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 2,
            "source": "acp",
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "c1",
            "status": "completed",
            "content": "body",
            "at": "2026-08-14T12:00:02.250Z",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    tool = next(x for x in _read_lines(path) if x["type"] == "tool_call")
    assert tool["elapsed_ms"] == 2250.0
    assert tool["started_at"] == "2026-08-14T12:00:00Z"
    assert tool["ended_at"] == "2026-08-14T12:00:02.25Z"


def test_writer_skips_empty_assistant_when_tools_ran(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "openai-http",
            "kind": "text",
            "channel": "thought",
            "text": "look up the user",
        },
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 2,
            "source": "openai-http",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "function_name": "find_user_id_by_name_zip",
            "args": {"zip": "19122"},
        },
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 3,
            "source": "ageval",
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "c1",
            "content": "yusuf_rossi_9620",
            "status": "completed",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="")
    types = [x["type"] for x in _read_lines(path)]
    assert types == ["turn", "turn", "tool_call", "observation", "terminal"]
    lines = _read_lines(path)
    assert lines[1]["role"] == "assistant"
    assert lines[1]["part"] == "thought"
    assert lines[1]["content"] == "look up the user"
    assert not any(x.get("role") == "assistant" and not x.get("part") for x in lines)


def test_writer_omits_timing_when_absent(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "acp",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "function_name": "read",
            "status": "completed",
            "content": "x",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    tool = next(x for x in _read_lines(path) if x["type"] == "tool_call")
    assert "elapsed_ms" not in tool
    assert "started_at" not in tool
    assert "ended_at" not in tool


def test_acp_mapper_copies_vendor_elapsed_and_at(tmp_path: Path) -> None:
    events = (
        {
            "type": "session_update",
            "session_id": "s1",
            "at": "2026-08-14T12:00:00Z",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "c1",
                "title": "ls",
                "kind": "execute",
                "status": "pending",
                "rawInput": {"command": "ls"},
                "startedAt": "2026-08-14T12:00:00Z",
            },
        },
        {
            "type": "session_update",
            "session_id": "s1",
            "at": "2026-08-14T12:00:01.5Z",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "c1",
                "status": "completed",
                "content": [{"type": "content", "content": {"type": "text", "text": "ok"}}],
                "durationMs": 1500,
                "endedAt": "2026-08-14T12:00:01.5Z",
            },
        },
    )
    mapped = acp_session_events_to_ageval(events)
    tools = [e for e in mapped if e.get("kind") == "tool"]
    assert tools[0]["at"] == "2026-08-14T12:00:00Z"
    assert tools[0]["started_at"] == "2026-08-14T12:00:00Z"
    assert tools[-1]["elapsed_ms"] == 1500.0
    path = _write(tmp_path, events=mapped, prompt="p", final_text="done")
    tool = next(x for x in _read_lines(path) if x["type"] == "tool_call")
    assert tool["elapsed_ms"] == 1500.0


def test_acp_mapper_copies_at_onto_text_and_core_derives_thought_elapsed(
    tmp_path: Path,
) -> None:
    events = (
        {
            "type": "session_update",
            "session_id": "s1",
            "channel": "thought",
            "text": "Now",
            "at": "2026-08-14T12:00:00.000Z",
        },
        {
            "type": "session_update",
            "session_id": "s1",
            "channel": "thought",
            "text": " write it.",
            "at": "2026-08-14T12:00:01.250Z",
        },
        {
            "type": "session_update",
            "session_id": "s1",
            "at": "2026-08-14T12:00:01.300Z",
            "title": "bash",
            "kind": "execute",
            "tool_call_id": "c1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "c1",
                "title": "echo hi",
                "kind": "execute",
                "status": "pending",
            },
        },
    )
    mapped = acp_session_events_to_ageval(events)
    texts = [e for e in mapped if e.get("kind") == "text"]
    assert all(e.get("at") for e in texts)
    tools = [e for e in mapped if e.get("kind") == "tool"]
    assert tools[0]["args"] == {"command": "echo hi"}
    assert not any(
        e.get("kind") == "tool" and e.get("seq", 0) > tools[-1]["seq"] for e in mapped[1:]
    )
    path = _write(tmp_path, events=mapped, prompt="p", final_text="done")
    lines = _read_lines(path)
    thought = next(x for x in lines if x.get("part") == "thought")
    assert thought["elapsed_ms"] == 1250.0
    tool = next(x for x in lines if x["type"] == "tool_call")
    assert tool["args"] == {"command": "echo hi"}
    assert [x["type"] for x in lines] == [
        "turn",
        "turn",
        "tool_call",
        "turn",
        "terminal",
    ]


def test_codex_read_args_from_locations_and_list_title(tmp_path: Path) -> None:
    """Codex ACP omits rawInput on read/listFiles; path is locations or title."""
    events = (
        {
            "type": "session_update",
            "session_id": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_read",
                "kind": "read",
                "title": "Read file '/attempt/workspace/records_1.jsonl'",
                "status": "completed",
                "locations": [{"path": "/attempt/workspace/records_1.jsonl"}],
            },
        },
        {
            "type": "session_update",
            "session_id": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_ls",
                "kind": "read",
                "title": "List files in 'workspace'",
                "status": "completed",
            },
        },
    )
    mapped = acp_session_events_to_ageval(events)
    tools = [e for e in mapped if e.get("kind") == "tool"]
    by_id = {e["tool_call_id"]: e for e in tools}
    assert by_id["call_read"]["args"] == {"path": "/attempt/workspace/records_1.jsonl"}
    assert by_id["call_ls"]["args"] == {"path": "workspace"}
    path = _write(tmp_path, events=mapped, prompt="p", final_text="done")
    folded = [x for x in _read_lines(path) if x["type"] == "tool_call"]
    args = {x["tool_call_id"]: x["args"] for x in folded}
    assert args["call_read"] == {"path": "/attempt/workspace/records_1.jsonl"}
    assert args["call_ls"] == {"path": "workspace"}


def test_writer_keeps_explicit_ended_at_over_later_at(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "acp",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "function_name": "read",
            "started_at": "2026-08-14T12:00:00Z",
            "at": "2026-08-14T12:00:00Z",
        },
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 2,
            "source": "acp",
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "c1",
            "status": "completed",
            "content": "body",
            "ended_at": "2026-08-14T12:00:01Z",
            "at": "2026-08-14T12:00:03Z",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    tool = next(x for x in _read_lines(path) if x["type"] == "tool_call")
    assert tool["ended_at"] == "2026-08-14T12:00:01Z"
    assert tool["elapsed_ms"] == 1000.0


def test_writer_drops_nonfinite_elapsed_ms(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "acp",
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "c1",
            "function_name": "read",
            "status": "completed",
            "content": "x",
            "elapsed_ms": float("inf"),
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    tool = next(x for x in _read_lines(path) if x["type"] == "tool_call")
    assert "elapsed_ms" not in tool


def _text(
    *,
    seq: int,
    channel: str,
    text: str,
    elapsed_ms: float | None = None,
    source: str = "acp",
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "schema": EVENT_SCHEMA_VERSION,
        "seq": seq,
        "source": source,
        "kind": "text",
        "channel": channel,
        "text": text,
    }
    if elapsed_ms is not None:
        ev["elapsed_ms"] = elapsed_ms
    return ev


def _tool(
    *,
    seq: int,
    call_id: str,
    phase: str,
    status: str = "completed",
    content: str | None = None,
    elapsed_ms: float | None = None,
    function_name: str = "read",
    source: str = "acp",
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "schema": EVENT_SCHEMA_VERSION,
        "seq": seq,
        "source": source,
        "kind": "tool",
        "phase": phase,
        "tool_call_id": call_id,
        "function_name": function_name,
        "status": status,
    }
    if content is not None:
        ev["content"] = content
    if elapsed_ms is not None:
        ev["elapsed_ms"] = elapsed_ms
    return ev


def test_writer_interleaves_thought_and_tool_in_seq_order(tmp_path: Path) -> None:
    events = (
        _text(seq=1, channel="thought", text="thought A", elapsed_ms=8000),
        _tool(seq=2, call_id="t1", phase="start", status="pending"),
        _tool(seq=3, call_id="t1", phase="update", content="a-out", elapsed_ms=12),
        _text(seq=4, channel="thought", text="thought B", elapsed_ms=5000),
        _tool(seq=5, call_id="t2", phase="start", status="pending", function_name="exec"),
        _tool(
            seq=6,
            call_id="t2",
            phase="update",
            content="b-out",
            elapsed_ms=20,
            function_name="exec",
        ),
        _text(seq=7, channel="assistant", text="done", elapsed_ms=3000),
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    lines = _read_lines(path)
    shape = []
    for row in lines:
        if row["type"] == "turn" and row.get("part") == "thought":
            shape.append(("thought", row["content"], row.get("elapsed_ms")))
        elif row["type"] == "tool_call":
            shape.append(("tool", row["tool_call_id"], row.get("elapsed_ms")))
        elif row["type"] == "observation":
            shape.append(("obs", row["tool_call_id"], None))
        elif row["type"] == "turn" and row.get("role") == "user":
            shape.append(("user", row["content"], None))
        elif row["type"] == "turn" and row.get("role") == "assistant":
            shape.append(("assistant", row["content"], row.get("elapsed_ms")))
        elif row["type"] == "terminal":
            shape.append(("terminal", None, None))
    assert shape == [
        ("user", "p", None),
        ("thought", "thought A", 8000.0),
        ("tool", "t1", 12.0),
        ("obs", "t1", None),
        ("thought", "thought B", 5000.0),
        ("tool", "t2", 20.0),
        ("obs", "t2", None),
        ("assistant", "done", 3000.0),
        ("terminal", None, None),
    ]
    assert lines[0]["role"] == "user"


def test_writer_merges_consecutive_thoughts_without_tool(tmp_path: Path) -> None:
    events = (
        _text(seq=1, channel="thought", text="A", elapsed_ms=10),
        _text(seq=2, channel="thought", text="B", elapsed_ms=20),
        _text(seq=3, channel="assistant", text="ok"),
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="ok")
    lines = _read_lines(path)
    thoughts = [x for x in lines if x.get("part") == "thought"]
    assert len(thoughts) == 1
    assert thoughts[0]["content"] == "AB"
    assert thoughts[0]["elapsed_ms"] == 30.0
    assert [x["type"] for x in lines] == ["turn", "turn", "turn", "terminal"]


def test_writer_does_not_copy_thought_elapsed_onto_final_assistant(
    tmp_path: Path,
) -> None:
    events = (
        _text(seq=1, channel="thought", text="plan", elapsed_ms=9000),
        _tool(seq=2, call_id="t1", phase="start", status="pending"),
        _tool(seq=3, call_id="t1", phase="update", content="out", elapsed_ms=8),
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    lines = _read_lines(path)
    thought = next(x for x in lines if x.get("part") == "thought")
    assistant = next(
        x
        for x in lines
        if x["type"] == "turn" and x.get("role") == "assistant" and x.get("part") != "thought"
    )
    assert thought["elapsed_ms"] == 9000.0
    assert "elapsed_ms" not in assistant


def test_writer_omits_thought_elapsed_when_absent(tmp_path: Path) -> None:
    events = (
        _text(seq=1, channel="thought", text="plan"),
        _tool(seq=2, call_id="t1", phase="update", content="out", status="completed"),
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    thought = next(x for x in _read_lines(path) if x.get("part") == "thought")
    assert "elapsed_ms" not in thought
    assert "started_at" not in thought


def test_writer_flushes_assistant_when_a_tool_follows(tmp_path: Path) -> None:
    events = (
        _text(seq=1, channel="assistant", text="mid", elapsed_ms=1100),
        _tool(seq=2, call_id="t1", phase="update", content="out", elapsed_ms=5),
        _text(seq=3, channel="assistant", text="end", elapsed_ms=400),
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="end")
    lines = _read_lines(path)
    assistants = [
        x
        for x in lines
        if x["type"] == "turn" and x.get("role") == "assistant" and x.get("part") != "thought"
    ]
    assert [x["content"] for x in assistants] == ["mid", "end"]
    assert assistants[0]["elapsed_ms"] == 1100.0
    assert assistants[1]["elapsed_ms"] == 400.0
    types = [x["type"] for x in lines]
    assert types == ["turn", "turn", "tool_call", "observation", "turn", "terminal"]


def test_writer_drops_invalid_timing(tmp_path: Path) -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "seq": 1,
            "source": "acp",
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "function_name": "read",
            "elapsed_ms": -3,
            "started_at": "not-a-time",
            "status": "completed",
            "content": "x",
        },
    )
    path = _write(tmp_path, events=events, prompt="p", final_text="done")
    tool = next(x for x in _read_lines(path) if x["type"] == "tool_call")
    assert "elapsed_ms" not in tool
    assert "started_at" not in tool


def test_terminal_keeps_usage_extra_and_copies_latency_ms(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        events=(),
        prompt="p",
        final_text="ok",
        usage={
            "prompt_tokens": 9,
            "completion_tokens": 4,
        },
        extra={"foo": "bar", "reasoning_tokens": 3},
        metadata={"executor_kind": "openai-http", "latency_ms": 142.5, "turn_index": 1},
    )
    terminal = next(x for x in _read_lines(path) if x["type"] == "terminal")
    assert terminal["usage"]["prompt_tokens"] == 9
    assert terminal["usage"]["completion_tokens"] == 4
    assert terminal["extra"]["foo"] == "bar"
    assert terminal["extra"]["reasoning_tokens"] == 3
    assert "extra" not in terminal["usage"]
    assert terminal["elapsed_ms"] == 142.5
    assert terminal["metadata"]["latency_ms"] == 142.5


def test_terminal_omits_elapsed_ms_when_invoke_latency_missing(tmp_path: Path) -> None:
    path = _write(tmp_path, events=(), prompt="p", final_text="ok", usage=None)
    terminal = next(x for x in _read_lines(path) if x["type"] == "terminal")
    assert "elapsed_ms" not in terminal
    assert terminal["usage"] is None


def test_terminal_prefers_metadata_elapsed_ms_over_latency_ms(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        events=(),
        prompt="p",
        final_text="ok",
        metadata={"elapsed_ms": 50, "latency_ms": 999},
    )
    terminal = next(x for x in _read_lines(path) if x["type"] == "terminal")
    assert terminal["elapsed_ms"] == 50.0


def test_turn_rows_stamps_profile_id_on_every_row() -> None:
    events = (
        {
            "schema": EVENT_SCHEMA_VERSION,
            "kind": "text",
            "channel": "assistant",
            "text": "hi",
            "source": "openai-http",
        },
    )
    rows = turn_rows(
        prompt="hello",
        events=events,
        final_text="hi",
        structured=None,
        usage=None,
        ok=True,
        error=None,
        metadata={"profile_id": "user", "turn_index": 1, "executor_kind": "openai-http"},
    )
    assert [r["type"] for r in rows] == ["turn", "turn", "terminal"]
    assert all(r.get("profile_id") == "user" for r in rows)
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"


def test_write_attempt_keeps_invoke_order_across_profiles(tmp_path: Path) -> None:
    user_turn = turn_rows(
        prompt="customer",
        events=(
            {
                "schema": EVENT_SCHEMA_VERSION,
                "kind": "text",
                "channel": "assistant",
                "text": "need a refund",
                "source": "openai-http",
            },
        ),
        final_text="need a refund",
        structured=None,
        usage=None,
        ok=True,
        error=None,
        metadata={"profile_id": "user", "turn_index": 1},
    )
    svc_turn = turn_rows(
        prompt="agent",
        events=(
            {
                "schema": EVENT_SCHEMA_VERSION,
                "kind": "text",
                "channel": "assistant",
                "text": "I can help",
                "source": "openai-http",
            },
        ),
        final_text="I can help",
        structured=None,
        usage=None,
        ok=True,
        error=None,
        metadata={"profile_id": "service", "turn_index": 2},
    )
    path = write_attempt_trajectory(tmp_path / "run", [user_turn, svc_turn])
    lines = _read_lines(path)
    assert [x["type"] for x in lines] == [
        "turn",
        "turn",
        "terminal",
        "turn",
        "turn",
        "terminal",
    ]
    assert [x["profile_id"] for x in lines] == [
        "user",
        "user",
        "user",
        "service",
        "service",
        "service",
    ]
    assert lines[2]["turn_index"] == 1
    assert lines[5]["turn_index"] == 2


def test_evaluation_observation_omits_user_row(tmp_path: Path) -> None:
    rows = turn_rows(
        prompt="hidden gold body",
        events=(
            {
                "schema": EVENT_SCHEMA_VERSION,
                "seq": 1,
                "source": "openai-http",
                "kind": "text",
                "channel": "assistant",
                "text": "score 1",
            },
        ),
        final_text="score 1",
        structured=None,
        usage={"prompt_tokens": 2, "completion_tokens": 1},
        extra=None,
        ok=True,
        error=None,
        metadata={"profile_id": "judge", "turn_index": 1, "executor_kind": "openai-http"},
        include_user=False,
    )
    roles = [row.get("role") for row in rows if row.get("type") == "turn"]
    assert "user" not in roles
    assert any(row.get("type") == "terminal" for row in rows)
    assert all("hidden gold body" not in json.dumps(row) for row in rows)
    path = write_evaluation_observation(tmp_path / "run", [rows])
    assert path == tmp_path / "run" / "evaluation" / "observation.jsonl"
    dumped = path.read_text(encoding="utf-8")
    assert "hidden gold body" not in dumped
    assert '"role": "assistant"' in dumped
