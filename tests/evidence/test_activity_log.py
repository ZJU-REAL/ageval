"""activity.jsonl writer, crash tail, and message projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ageval.config.errors import ConfigError
from ageval.evidence.activity import (
    ACTIVITY_FORMAT,
    ActivityLog,
    ActivityScope,
    chat_messages_for_wire,
    project_messages,
    reconcile_inflight_tail,
)


def _header_payload() -> dict[str, object]:
    return {
        "run_id": "run01",
        "trial_id": "trial01",
        "attempt_id": "attempt01",
        "task_id": "tau2-dialog-min",
        "attempt_index": 0,
        "suite_run_id": None,
        "locked_config_digest": "sha256:abc",
        "environment_kind": "local",
        "environment_nonce": "nce_abc",
        "environment_handle": None,
    }


def test_append_fsync_roundtrip_and_redacts(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog.open(path)
    log.append(
        request_id="att_run01",
        kind="attempt",
        status="completed",
        payload=_header_payload(),
    )
    log.append(
        request_id="req_1",
        kind="invoke",
        status="in_flight",
        payload={
            "session_id": "sess_solver_default_main_1",
            "turn_index": 1,
            "prompt": "token sk-abcdefghijklmnop",
            "tools_digest": None,
            "messages_digest": None,
            "explicit_messages": None,
        },
    )
    opened = ActivityLog.open(path)
    assert opened.corrupt is None
    assert opened.facts == []
    assert [record.seq for record in opened.records] == [1, 2]
    assert opened.records[1].payload["prompt"] == "token [REDACTED:secret]"
    assert opened.header() is not None
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "sk-abcdefghijklmnop" not in text


def test_truncated_tail_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog.open(path)
    log.append(request_id="att", kind="attempt", status="completed", payload=_header_payload())
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw + '{"format":"ageval.activity/1","seq":2', encoding="utf-8")
    opened = ActivityLog.open(path)
    assert opened.corrupt is None
    assert opened.facts == ["recovery_tail_truncated"]
    assert len(opened.records) == 1
    opened.append(
        request_id="phase_environment",
        kind="phase",
        status="in_flight",
        payload={"phase": "environment"},
    )
    assert opened.records[-1].seq == 2


def test_middle_line_is_corrupt_and_keeps_header(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog.open(path)
    log.append(request_id="att", kind="attempt", status="completed", payload=_header_payload())
    log.append(
        request_id="phase_environment",
        kind="phase",
        status="in_flight",
        payload={"phase": "environment"},
    )
    log.append(
        request_id="phase_environment",
        kind="phase",
        status="completed",
        payload={
            "phase": "environment",
            "elapsed_ms": 1.0,
            "limit_reached": None,
            "checkpoint_seq": None,
        },
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = "{not-json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    opened = ActivityLog.open(path)
    assert opened.corrupt is not None
    header = opened.header()
    assert header is not None
    assert header.payload["attempt_id"] == "attempt01"


def test_invalid_format_raises(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    path.write_text(
        json.dumps(
            {
                "format": "ageval.activity/0",
                "seq": 1,
                "at": "t",
                "request_id": "a",
                "kind": "attempt",
                "status": "completed",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        ActivityLog.open(path)
    assert caught.value.error_code == "invalid_format"
    assert caught.value.location == "/format"


def test_header_update_rewrites_seq_one(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog.open(path)
    log.append(request_id="att", kind="attempt", status="completed", payload=_header_payload())
    log.append(
        request_id="phase_environment",
        kind="phase",
        status="in_flight",
        payload={"phase": "environment"},
    )
    log.update_attempt_header(environment_handle={"container_id": "ageval-1"})
    opened = ActivityLog.open(path)
    assert opened.records[0].payload["environment_handle"] == {"container_id": "ageval-1"}
    assert opened.records[1].kind == "phase"
    assert opened.records[0].format == ACTIVITY_FORMAT


def test_project_messages_respects_compaction(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "old"}])
    scope.record_model_turn_completed(1, assistant_text="old-answer", tool_calls=[])
    scope.record_tool_call_in_flight("call_1", "execute", "execute", {"command": "ls"})
    scope.record_tool_call_completed(
        "call_1", outcome="ok", exit_code=0, content="listed\n", checkpoint_seq=4
    )
    scope.record_compaction(
        source="parent_executor",
        replaces_through_seq=4,
        summary_messages=[{"role": "user", "content": "summary"}],
        checkpoint_seq=5,
    )
    scope.record_model_turn_in_flight(2, [{"role": "user", "content": "next"}])
    scope.record_model_turn_completed(2, assistant_text="next-answer")
    projected = project_messages(log.records, "sess_a")
    assert projected[0] == {"role": "user", "content": "summary"}
    assert projected[1]["role"] == "user"
    assert projected[1]["content"] == "next"
    assert projected[2]["role"] == "assistant"
    assert projected[2]["content"] == "next-answer"
    assert all("old" not in json.dumps(item) for item in projected)


def test_project_messages_pairs_provider_ids_once_after_abort(tmp_path: Path) -> None:
    """Each tool result is emitted once, under the assistant's provider id.

    The next model turn's in-flight tail repeats those results with the
    provider id. After the process is cut, that tail is not folded, so the
    completed tool record has to carry the provider id itself.
    """
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "go"}])
    scope.record_model_turn_completed(
        1,
        assistant_text="run two",
        tool_calls=[
            {"command": "echo one", "tool_call_id": "toolu_a"},
            {"command": "echo two", "tool_call_id": "toolu_b"},
        ],
    )
    scope.record_tool_call_in_flight("bash_1", "bash", "execute", {"command": "echo one"})
    scope.record_tool_call_completed("bash_1", outcome="ok", exit_code=0, content="one\n")
    scope.record_tool_call_in_flight("bash_2", "bash", "execute", {"command": "echo two"})
    scope.record_tool_call_completed("bash_2", outcome="ok", exit_code=0, content="two\n")
    scope.record_model_turn_in_flight(
        2,
        [
            {"role": "tool", "tool_call_id": "toolu_a", "content": "TEMPLATE one"},
            {"role": "tool", "tool_call_id": "toolu_b", "content": "TEMPLATE two"},
            {"role": "user", "content": "keep-this-note"},
        ],
    )
    scope.record_model_turn_completed(
        2,
        assistant_text="run three",
        tool_calls=[{"command": "echo three", "tool_call_id": "toolu_c"}],
    )
    scope.record_tool_call_in_flight("bash_3", "bash", "execute", {"command": "echo three"})
    scope.record_tool_call_completed("bash_3", outcome="ok", exit_code=0, content="three\n")
    scope.record_model_turn_in_flight(
        3,
        [{"role": "tool", "tool_call_id": "toolu_c", "content": "TEMPLATE three"}],
    )
    scope.record_model_turn_aborted(3, reason="process_interrupted")

    projected = project_messages(log.records, "sess_a")
    assert [item["role"] for item in projected] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "user",
        "assistant",
        "tool",
    ]
    assert [item["tool_call_id"] for item in projected if item["role"] == "tool"] == [
        "toolu_a",
        "toolu_b",
        "toolu_c",
    ]
    assert [item["content"] for item in projected if item["role"] == "tool"] == [
        "one\n",
        "two\n",
        "three\n",
    ]
    blob = json.dumps(projected)
    assert "bash_" not in blob
    assert "TEMPLATE" not in blob
    assert projected[-2]["role"] == "assistant"
    assert projected[-1]["role"] == "tool"
    assert projected[1]["tool_calls"] == [
        {
            "id": "toolu_a",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo one"}'},
        },
        {
            "id": "toolu_b",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo two"}'},
        },
    ]
    assert projected[5]["tool_calls"] == [
        {
            "id": "toolu_c",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo three"}'},
        }
    ]
    assert projected[4] == {"role": "user", "content": "keep-this-note"}

    from ageval.plugins.contrib.anthropic_http.executor import anthropic_messages

    _system, chat = anthropic_messages("unused", projected)
    uses: list[str] = []
    results: list[tuple[str, str]] = []
    for turn in chat:
        content = turn["content"]
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                assert turn["role"] == "assistant"
                uses.append(str(block["id"]))
            elif block.get("type") == "tool_result":
                assert turn["role"] == "user"
                results.append((str(block["tool_use_id"]), str(block["content"])))
    assert uses == ["toolu_a", "toolu_b", "toolu_c"]
    assert results == [
        ("toolu_a", "one\n"),
        ("toolu_b", "two\n"),
        ("toolu_c", "three\n"),
    ]
    assert chat[-1]["role"] == "user"
    assert chat[-1]["content"][0]["type"] == "tool_result"


def test_project_messages_leaves_local_id_when_the_assistant_has_none(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "go"}])
    scope.record_model_turn_completed(1, assistant_text="run", tool_calls=[{"command": "echo hi"}])
    scope.record_tool_call_in_flight("bash_1", "bash", "execute", {"command": "echo hi"})
    scope.record_tool_call_completed("bash_1", outcome="ok", exit_code=0, content="hi\n")

    projected = project_messages(log.records, "sess_a")
    assistant = next(item for item in projected if item["role"] == "assistant")
    tool = next(item for item in projected if item["role"] == "tool")
    assert "tool_calls" not in assistant
    assert tool["tool_call_id"] == "bash_1"
    assert tool["content"] == "hi\n"


def test_chat_messages_for_wire_puts_tool_calls_on_the_assistant() -> None:
    recorded = {
        "role": "assistant",
        "content": "run",
        "extra": {
            "actions": [
                {"command": "echo one", "tool_call_id": "toolu_a"},
                {"command": "echo two", "tool_call_id": "toolu_b"},
            ]
        },
    }
    wired = chat_messages_for_wire([{"role": "user", "content": "go"}, recorded])
    assert "tool_calls" not in recorded
    assert recorded["extra"]["actions"][0]["tool_call_id"] == "toolu_a"
    assert [item["role"] for item in wired] == ["user", "assistant"]
    assert "extra" not in wired[1]
    assert wired[1]["tool_calls"] == [
        {
            "id": "toolu_a",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo one"}'},
        },
        {
            "id": "toolu_b",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "echo two"}'},
        },
    ]
    stripped = {key: value for key, value in wired[1].items() if key != "extra"}
    assert stripped["role"] == "assistant"
    assert stripped["tool_calls"][0]["id"] == "toolu_a"

    preferred = chat_messages_for_wire(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "toolu_real",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                    }
                ],
                "extra": {"actions": [{"command": "ls", "tool_call_id": "bash_1"}]},
            }
        ]
    )
    assert preferred[0]["role"] == "assistant"
    assert preferred[0]["tool_calls"][0]["id"] == "toolu_real"
    assert "extra" not in preferred[0]

    named = chat_messages_for_wire(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "toolu_n", "name": "bash", "arguments": {"command": "pwd"}}],
            }
        ]
    )
    assert named[0]["tool_calls"] == [
        {
            "id": "toolu_n",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"command": "pwd"}'},
        }
    ]
    assert chat_messages_for_wire([{"role": "user", "content": "hi"}]) == [
        {"role": "user", "content": "hi"}
    ]


def test_reconcile_aborts_model_and_interrupts_unsafe_tool(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "hi"}])
    reconcile_inflight_tail(scope)
    assert scope.inflight_step() is None
    assert log.latest_status(kind="model_turn", request_id="mt_req_a_1") == "aborted"

    scope.record_tool_call_in_flight(
        "call_9", "execute", "execute", {"command": "rm"}, replay_safe=False
    )
    reconcile_inflight_tail(scope, partial_output="partial")
    completed = log.records_for(kind="tool_call", request_id="tool_sess_a_call_9")[-1]
    assert completed.status == "completed"
    assert completed.payload["outcome"] == "interrupted"
    assert completed.payload["content"] == "partial"


def test_replay_safe_tool_is_aborted_for_rerun(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_tool_call_in_flight("call_r", "read", "read", {"path": "a"}, replay_safe=True)
    reconcile_inflight_tail(scope)
    assert log.latest_status(kind="tool_call", request_id="tool_sess_a_call_r") == "aborted"
    assert scope.inflight_step() is None


def test_admitted_invokes_stop_at_seal_run(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    inflight = {
        "session_id": "sess",
        "turn_index": 1,
        "prompt": "p",
        "tools_digest": None,
        "messages_digest": None,
        "explicit_messages": None,
    }
    done = {
        "session_id": "sess",
        "turn_index": 1,
        "ok": True,
        "text": "t",
        "structured": None,
        "tool_calls": [],
        "usage": None,
        "error": None,
        "checkpoint_seq": None,
    }
    log.append(request_id="req_a", kind="invoke", status="in_flight", payload=inflight)
    log.append(request_id="req_a", kind="invoke", status="completed", payload=done)
    log.append(
        request_id="phase_seal_run",
        kind="phase",
        status="completed",
        payload={
            "phase": "seal_run",
            "elapsed_ms": 10.0,
            "limit_reached": None,
            "checkpoint_seq": None,
        },
    )
    eval_payload = dict(inflight)
    eval_payload["turn_index"] = 1
    log.append(request_id="req_eval", kind="invoke", status="in_flight", payload=eval_payload)
    assert log.admitted_run_invoke_count() == 1
    assert log.invoke_already_admitted("req_a")
    assert log.phase_elapsed_ms("seal_run") == 10.0


def test_step_elapsed_ms_counts_without_an_invoke_completed_line(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog.open(path)
    log.append(
        request_id="phase_run",
        kind="phase",
        status="in_flight",
        payload={"phase": "run"},
    )
    clock = iter((12000.0, 25000.0, 25000.0))
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.elapsed_ms_provider = lambda: next(clock)
    scope.record_tool_call_in_flight("call_1", "execute", "execute", {"command": "ls"})
    scope.record_tool_call_completed("call_1", outcome="ok", exit_code=0, content="listed")
    scope.record_model_turn_completed(1, assistant_text="next")
    completed = [
        record
        for record in log.records
        if record.status == "completed" and record.kind in {"tool_call", "model_turn"}
    ]
    assert [record.payload["elapsed_ms"] for record in completed] == [12000.0, 25000.0]
    assert log.phase_elapsed_ms("run") == 25000.0
    assert not any(record.kind == "invoke" for record in log.records)

    # A finished step written before this clock existed is still a valid line.
    bare = {
        "format": ACTIVITY_FORMAT,
        "seq": len(log.records) + 1,
        "at": "2026-10-25T06:00:05.120Z",
        "request_id": "mt_req_a_0",
        "kind": "model_turn",
        "status": "completed",
        "payload": {
            "session_id": "sess_a",
            "invoke_request_id": "req_a",
            "step_index": 0,
            "assistant_text": "old",
            "thought": None,
            "tool_calls": [],
            "usage": None,
            "stop_reason": None,
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(bare) + "\n")
    opened = ActivityLog.open(path)
    assert opened.corrupt is None
    assert opened.phase_elapsed_ms("run") == 25000.0


def test_model_turn_delta_rows_are_valid_and_projection_ignores_them(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog.open(path, sentinels=("SECRET_VALUE",))
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "hi"}])
    delta = scope.record_model_turn_delta(
        1,
        channel="assistant",
        text="prefix SECRET_VALUE suffix",
    )
    scope.record_model_turn_delta(
        1,
        channel="tool",
        text='{"q":',
        tool_index=0,
        tool_call_id="call_1",
    )
    assert delta.status == "delta"
    assert "SECRET_VALUE" not in delta.payload["text"]
    assert "[REDACTED:secret]" in delta.payload["text"]
    assert scope.project_messages() == []
    scope.record_model_turn_completed(1, assistant_text="answer")
    reopened = ActivityLog.open(path, sentinels=("SECRET_VALUE",))
    assert reopened.corrupt is None
    assert [record.status for record in reopened.records] == [
        "in_flight",
        "delta",
        "delta",
        "completed",
    ]
    assert reopened.latest_status(kind="model_turn", request_id="mt_req_a_1") == "completed"


def test_mark_aborted_keeps_live_delta_text(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    scope = ActivityScope(log, session_id="sess_a", invoke_request_id="req_a")
    scope.record_model_turn_in_flight(1, [{"role": "user", "content": "hi"}])
    scope.record_model_turn_delta(1, channel="assistant", text="partial ")
    scope.record_model_turn_delta(1, channel="thought", text="thinking")
    aborted = scope.mark_aborted("mt_req_a_1", reason="process_interrupted")
    assert aborted.status == "aborted"
    assert aborted.payload["partial_text"] == "partial "
    assert aborted.payload["partial_thought"] == "thinking"
