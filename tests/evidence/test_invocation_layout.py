"""Invocation directory field contract."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.application.suite.suite_usage import usage_from_trajectory
from ageval.evidence.invocation import read_invocation_payload
from ageval.evidence.store import AttemptEvidenceStore
from ageval.evidence.trajectory import turn_rows, write_attempt_trajectory
from ageval.model.usage import Usage
from ageval.plugins.agent_result import AgentResult
from ageval.runtime.agent_service_evidence import seal_invoke_result


def test_minimal_fields_present(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "e", attempt_id="attempt_x")
    h = store.begin_invocation(
        profile_id="codex-mini",
        executor_kind="codex",
        model="gpt-5.4-mini",
    )
    h.write_request(
        {
            "messages": [{"role": "user", "content": "Return JSON"}],
            "profile_id": "codex-mini",
            "executor_kind": "codex",
            "model": "gpt-5.4-mini",
        }
    )
    h.append_event({"type": "backend", "payload": {"msg": "partial"}})
    h.write_stderr("diag line\n")
    h.seal(
        status="completed",
        final_response={
            "content": '{"answer": 42}',
            "structured_output": {"answer": 42},
            "usage": {"input_tokens": 1},
            "session": {"reusable": False, "handle": None},
        },
        latency_ms=100.0,
    )
    d = h.directory
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    for key in (
        "invocation_id",
        "attempt_id",
        "profile_id",
        "executor_kind",
        "model",
        "started_at",
        "finished_at",
        "status",
        "latency_ms",
    ):
        assert key in meta
    req = json.loads((d / "request.json").read_text(encoding="utf-8"))
    assert req["messages"][0]["role"] == "user"
    events = (d / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) >= 1
    final = json.loads((d / "final-response.json").read_text(encoding="utf-8"))
    assert final["structured_output"]["answer"] == 42
    assert (d / "stderr.txt").read_text(encoding="utf-8").startswith("diag")
    assert h.relative_path.startswith("agent/invocations/")


def test_evaluate_surface_lives_under_evaluation(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "e", attempt_id="attempt_y")
    agent = store.begin_invocation(profile_id="solver", executor_kind="acp", model="m")
    judge = store.begin_invocation(
        profile_id="judge",
        executor_kind="openai-http",
        model="g",
        surface="evaluate",
    )
    assert agent.relative_path.startswith("agent/invocations/")
    assert judge.relative_path.startswith("evaluation/invocations/")
    assert store.list_invocations() == [agent.directory]
    assert store.list_evaluation_invocations() == [judge.directory]
    assert not (tmp_path / "e" / "agent" / "invocations" / judge.directory.name).exists()


def test_append_supplement_after_seal(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "e", attempt_id="attempt_z")
    h = store.begin_invocation(profile_id="p", executor_kind="openai-http", model="m")
    h.write_request({"messages": [{"role": "user", "content": "x"}]})
    h.append_event(
        {
            "kind": "tool",
            "phase": "start",
            "tool_call_id": "c1",
            "function_name": "lookup",
        }
    )
    h.seal(status="completed", final_response={"content": ""}, latency_ms=1.0)
    h.append_supplement(
        {
            "kind": "tool",
            "phase": "update",
            "tool_call_id": "c1",
            "content": '{"ok": true}',
            "status": "completed",
            "source": "ageval",
        }
    )
    events = (h.directory / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 2
    update = json.loads(events[1])
    assert update["phase"] == "update"
    assert update["content"] == '{"ok": true}'
    meta = json.loads((h.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["event_count"] == 2


def test_partial_failure_no_final_response(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "e", attempt_id="attempt_y")
    for status in ("failed", "timeout", "cancelled", "crash"):
        h = store.begin_invocation(profile_id="p", executor_kind="codex", model="m")
        h.write_request({"messages": [{"role": "user", "content": status}]})
        h.append_event({"type": "lifecycle", "phase": status})
        h.seal(status=status, error=status, latency_ms=1.0)
        assert not (h.directory / "final-response.json").exists()
        meta = json.loads((h.directory / "metadata.json").read_text(encoding="utf-8"))
        assert meta["status"] == status
        assert "usage" not in meta
        assert "extra" not in meta


def test_failed_invoke_usage_lands_on_the_terminal(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "e", attempt_id="attempt_usage")
    handle = store.begin_invocation(profile_id="p", executor_kind="acp", model="m")
    handle.write_request({"messages": [{"role": "user", "content": "hi"}]})
    result = AgentResult(
        model="m",
        text="partial",
        structured=None,
        ok=False,
        error="acp_timeout",
        usage=Usage(prompt_tokens=4, completion_tokens=1, cost_usd=0.02),
        extra={"usage_partial": True, "usage_source": "prompt_usage+usage_update"},
    )
    assert seal_invoke_result(handle, result=result, latency_ms=12.0) is None
    assert not (handle.directory / "final-response.json").exists()
    meta = json.loads((handle.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert meta["error"] == "acp_timeout"
    assert meta["usage"]["prompt_tokens"] == 4
    assert meta["extra"]["usage_partial"] is True

    payload = read_invocation_payload(handle.directory)
    assert payload["ok"] is False
    assert payload["usage"]["cost_usd"] == 0.02
    assert payload["extra"]["usage_source"] == "prompt_usage+usage_update"
    rows = turn_rows(**payload, include_user=True)
    terminal = next(row for row in rows if row.get("type") == "terminal")
    assert terminal["ok"] is False
    assert terminal["usage"]["prompt_tokens"] == 4
    assert terminal["extra"]["usage_partial"] is True

    path = write_attempt_trajectory(tmp_path / "run", [rows])
    rolled = usage_from_trajectory(path)
    assert rolled["prompt_tokens"] == 4
    assert rolled["completion_tokens"] == 1
    assert rolled["cost_usd"] == 0.02
