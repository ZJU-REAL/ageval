"""Completed invokes are returned from the activity log and are not sent again."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.agent_binding import ScriptedBinder, ScriptedExecutor

from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import AttemptEvidenceStore
from ageval.model.errors import ModelConfigError, TransportStall
from ageval.plugins.agent_result import AgentResult
from ageval.runtime.parent_agent import ParentAgentService


class StallExhausted(Exception):
    pass


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


def test_fatal_completed_invoke_is_retried_with_one_logical_quota_slot(tmp_path: Path) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    failure = ModelConfigError("chat_http_403:insufficient balance")
    failing = ScriptedExecutor(
        script=[
            AgentResult(
                model="scripted-model",
                text="",
                structured=None,
                ok=False,
                error="ModelConfigError:chat_http_403:insufficient balance",
                failure=failure,
            )
        ]
    )
    first = _service(evidence, log, failing, limit=1)
    opened = first.open_session(profile_id="solver")
    session_id = opened["session_id"]
    request_id = f"req_{session_id}_turn_1"
    failed = first.invoke(
        session_id=session_id, prompt="hello", request_id=request_id, turn_index=1
    )
    assert failed["ok"] is False
    assert first.fatal_invoke == (
        "ModelConfigError",
        "ModelConfigError:chat_http_403:insufficient balance",
    )
    reopened_log = ActivityLog.open(log.path)
    assert reopened_log.admitted_run_invoke_count() == 0
    fatal_payload = reopened_log.records_for(kind="invoke", request_id=request_id)[-1].payload
    assert fatal_payload["fatal_invoke_kind"] == "ModelConfigError"

    second_executor = ScriptedExecutor()
    again = _service(evidence, reopened_log, second_executor, limit=1)
    assert again.fatal_invoke is None
    assert again.invoke_quota is not None
    again.invoke_quota.restore_used(reopened_log.admitted_run_invoke_count())
    again.open_session(profile_id="solver")
    retried = again.invoke(
        session_id=session_id, prompt="hello", request_id=request_id, turn_index=1
    )
    assert retried["ok"] is True
    assert second_executor.prompts == ["hello"]
    assert again.invoke_quota.remaining == 0
    completed = reopened_log.records_for(kind="invoke", request_id=request_id)
    assert [record.payload["ok"] for record in completed if record.status == "completed"] == [
        False,
        True,
    ]


def test_repeated_fatal_retries_keep_one_logical_quota_slot(tmp_path: Path) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log_path = tmp_path / "attempt" / "activity.jsonl"
    request_id = "req_sess_solver_default_main_1_turn_1"

    for _ in range(2):
        failing = ScriptedExecutor(
            script=[
                AgentResult(
                    model="scripted-model",
                    text="",
                    structured=None,
                    ok=False,
                    error="ModelConfigError:chat_http_403:insufficient balance",
                    failure=ModelConfigError("chat_http_403:insufficient balance"),
                )
            ]
        )
        service = _service(evidence, ActivityLog.open(log_path), failing, limit=1)
        opened = service.open_session(profile_id="solver")
        service.invoke(
            session_id=opened["session_id"],
            prompt="hello",
            request_id=request_id,
            turn_index=1,
        )
        assert ActivityLog.open(log_path).admitted_run_invoke_count() == 0

    passing = ScriptedExecutor()
    resumed = _service(evidence, ActivityLog.open(log_path), passing, limit=1)
    assert resumed.invoke_quota is not None
    resumed.invoke_quota.restore_used(ActivityLog.open(log_path).admitted_run_invoke_count())
    opened = resumed.open_session(profile_id="solver")
    result = resumed.invoke(
        session_id=opened["session_id"],
        prompt="hello",
        request_id=request_id,
        turn_index=1,
    )

    assert result["ok"] is True
    assert passing.prompts == ["hello"]
    assert resumed.invoke_quota is not None
    assert resumed.invoke_quota.remaining == 0
    completed = ActivityLog.open(log_path).records_for(kind="invoke", request_id=request_id)
    assert [record.payload["ok"] for record in completed if record.status == "completed"] == [
        False,
        False,
        True,
    ]


@pytest.mark.parametrize(
    ("error", "failure", "metadata", "expected"),
    [
        pytest.param(
            "ModelConfigError:chat_http_403:insufficient balance",
            ModelConfigError("chat_http_403:insufficient balance"),
            None,
            ("ModelConfigError", "ModelConfigError:chat_http_403:insufficient balance"),
            id="model-config",
        ),
        pytest.param(
            "TransportStall:HTTPError:503",
            TransportStall("HTTPError:503", kind="http"),
            None,
            ("TransportStall", "TransportStall:HTTPError:503"),
            id="transport-stall",
        ),
        pytest.param(
            "stall_exhausted",
            StallExhausted("TransportStall:TimeoutError:180"),
            {"stall_exhausted": True},
            ("StallExhausted", "StallExhausted:stall_exhausted"),
            id="stall-exhausted",
        ),
    ],
)
def test_every_fatal_result_class_is_recorded(
    tmp_path: Path,
    error: str,
    failure: BaseException,
    metadata: dict[str, object] | None,
    expected: tuple[str, str],
) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    executor = ScriptedExecutor(
        script=[
            AgentResult(
                model="scripted-model",
                text="",
                structured=None,
                ok=False,
                error=error,
                failure=failure,
                metadata=metadata,
                repeatable=False,
            )
        ]
    )
    service = _service(evidence, log, executor, limit=1)
    opened = service.open_session(profile_id="solver")
    request_id = f"req_{opened['session_id']}_turn_1"

    failed = service.invoke(
        session_id=opened["session_id"],
        prompt="hello",
        request_id=request_id,
        turn_index=1,
    )

    assert failed["ok"] is False
    assert service.fatal_invoke == expected
    assert log.admitted_run_invoke_count() == 0
    payload = log.records_for(kind="invoke", request_id=request_id)[-1].payload
    assert payload["fatal_invoke_kind"] == expected[0]


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        pytest.param(
            ModelConfigError("chat_http_403:insufficient balance"),
            "ModelConfigError",
            id="model-config",
        ),
        pytest.param(
            TransportStall("HTTPError:503", kind="http"),
            "TransportStall",
            id="transport-stall",
        ),
        pytest.param(
            StallExhausted("TransportStall:TimeoutError:180"),
            "StallExhausted",
            id="stall-exhausted",
        ),
    ],
)
def test_raised_fatal_invoke_crash_is_recorded(
    tmp_path: Path,
    failure: BaseException,
    kind: str,
) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    service = _service(evidence, log, ScriptedExecutor(raises=failure), limit=1)
    opened = service.open_session(profile_id="solver")
    request_id = f"req_{opened['session_id']}_turn_1"

    failed = service.invoke(
        session_id=opened["session_id"],
        prompt="hello",
        request_id=request_id,
        turn_index=1,
    )

    assert failed["ok"] is False
    assert service.fatal_invoke is not None
    assert service.fatal_invoke[0] == kind
    payload = log.records_for(kind="invoke", request_id=request_id)[-1].payload
    assert payload["fatal_invoke_kind"] == kind


def test_fatal_invoke_is_sticky_across_agent_sessions(tmp_path: Path) -> None:
    evidence = AttemptEvidenceStore(
        root=tmp_path / "attempt", attempt_id="attempt_a", run_id="run_a"
    )
    log = ActivityLog.open(tmp_path / "attempt" / "activity.jsonl")
    executor = ScriptedExecutor(
        script=[
            AgentResult(
                model="scripted-model",
                text="",
                structured=None,
                ok=False,
                error="TransportStall:HTTPError:503",
                failure=TransportStall("HTTPError:503", kind="http"),
                repeatable=False,
            ),
            AgentResult(
                model="scripted-model",
                text="",
                structured=None,
                ok=False,
                error="ModelConfigError:chat_http_403:insufficient balance",
                failure=ModelConfigError("chat_http_403:insufficient balance"),
                repeatable=False,
            ),
        ]
    )
    service = _service(evidence, log, executor, extra_profiles=("reviewer",))
    reviewer = service.open_session(profile_id="reviewer")
    service.invoke(
        session_id=reviewer["session_id"],
        prompt="review",
        request_id=f"req_{reviewer['session_id']}_turn_1",
        turn_index=1,
    )
    solver = service.open_session(profile_id="solver")
    service.invoke(
        session_id=solver["session_id"],
        prompt="solve",
        request_id=f"req_{solver['session_id']}_turn_1",
        turn_index=1,
    )

    assert service.fatal_invoke == (
        "TransportStall",
        "TransportStall:HTTPError:503",
    )


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
    extra_profiles: tuple[str, ...] = (),
) -> ParentAgentService:
    binder = ScriptedBinder(executor, extra_profiles=extra_profiles)
    service = ParentAgentService(
        attempt_id=evidence.attempt_id,
        binder=binder,
        agent_invocation_limit=limit,
        evidence_store=evidence,
        activity=log,
    )
    return service
