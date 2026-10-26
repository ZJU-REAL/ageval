"""Completed invokes are returned from the activity log and are not sent again."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.agent_binding import ScriptedBinder, ScriptedExecutor

from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import AttemptEvidenceStore
from ageval.runtime.parent_agent import ParentAgentService


@pytest.fixture(autouse=True)
def _scripted_invoke_is_online(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)


def test_completed_invoke_is_not_sent_again(tmp_path: Path) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    executor = ScriptedExecutor()
    first = _service(evidence, log, executor)
    opened = first.open_session(profile_id="solver")
    session_id = opened["session_id"]
    assert session_id == "sess_solver_default_main_1"
    request_id = f"req_{session_id}_turn_1"
    first_result = first.invoke(
        session_id=session_id, prompt="hello", request_id=request_id, turn_index=1
    )
    assert first_result["ok"] is True
    assert executor.prompts == ["hello"]
    assert log.latest_status(kind="invoke", request_id=request_id) == "completed"

    second_executor = ScriptedExecutor()
    again = _service(evidence, ActivityLog.open(log.path), second_executor)
    reopened = again.open_session(profile_id="solver")
    assert reopened["session_id"] == session_id
    replayed = again.invoke(
        session_id=session_id, prompt="hello", request_id=request_id, turn_index=1
    )
    assert replayed["ok"] is True
    assert replayed["text"] == first_result["text"]
    assert second_executor.prompts == []


def test_completed_invoke_replay_does_not_spend_another_slot(tmp_path: Path) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    first = _service(evidence, log, ScriptedExecutor(), limit=1)
    opened = first.open_session(profile_id="solver")
    session_id = opened["session_id"]
    request_id = f"req_{session_id}_turn_1"
    assert first.invoke(session_id=session_id, prompt="hello", request_id=request_id)["ok"] is True

    again = _service(evidence, ActivityLog.open(log.path), ScriptedExecutor(), limit=1)
    assert again.invoke_quota is not None
    again.invoke_quota.restore_used(ActivityLog.open(log.path).admitted_run_invoke_count())
    assert again.invoke_quota.remaining == 0
    again.open_session(profile_id="solver")
    replayed = again.invoke(session_id=session_id, prompt="hello", request_id=request_id)
    assert replayed["ok"] is True
    assert again.invoke_quota.remaining == 0
    refused = again.invoke(session_id=session_id, prompt="another", request_id="req_new")
    assert refused["error"] == "agent_invocation_limit"


def test_conflicting_prompt_is_alignment_mismatch(tmp_path: Path) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    service = _service(evidence, log, ScriptedExecutor())
    opened = service.open_session(profile_id="solver")
    session_id = opened["session_id"]
    request_id = f"req_{session_id}_turn_1"
    service.invoke(session_id=session_id, prompt="hello", request_id=request_id, turn_index=1)

    restarted = _service(evidence, ActivityLog.open(log.path), ScriptedExecutor())
    restarted.open_session(profile_id="solver")
    mismatch = restarted.invoke(
        session_id=session_id, prompt="different", request_id=request_id, turn_index=1
    )
    assert mismatch["error"] == "session_alignment_mismatch"
    assert restarted.fatal_error == "session_alignment_mismatch"


def _service(
    evidence: AttemptEvidenceStore,
    log: ActivityLog,
    executor: ScriptedExecutor,
    *,
    limit: int = 4,
) -> ParentAgentService:
    binder = ScriptedBinder(executor)
    service = ParentAgentService(
        attempt_id=evidence.attempt_id,
        binder=binder,
        agent_invocation_limit=limit,
        evidence_store=evidence,
        activity=log,
    )
    return service
