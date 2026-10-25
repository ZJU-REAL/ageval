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
