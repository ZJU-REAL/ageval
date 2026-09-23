"""Parent Agent Service: every ceiling holds before the external effect."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest
from tests.helpers.agent_binding import ScriptedBinder, ScriptedExecutor

from ageval.evidence.store import AttemptEvidenceStore
from ageval.runtime.agent_service_protocol import AgentServiceServer, agent_service_client_call
from ageval.runtime.parent_agent import (
    DEFAULT_INVOKE_TIMEOUT_SECONDS,
    AgentInvocationQuota,
    ParentAgentService,
    resolve_invoke_timeout_seconds,
)

ATTEMPT = "attempt_" + "a" * 16


def _service(
    tmp_path: Path,
    *,
    limit: int = 2,
    executor: ScriptedExecutor | None = None,
    deadline_monotonic: float | None = None,
    invoke_timeout_seconds: float = DEFAULT_INVOKE_TIMEOUT_SECONDS,
    evidence: bool = True,
    offline_env: str = "",
    extra_profiles: tuple[str, ...] = (),
) -> tuple[ParentAgentService, ScriptedExecutor]:
    backend = executor or ScriptedExecutor()
    store = (
        AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="run_x")
        if evidence
        else None
    )
    service = ParentAgentService(
        attempt_id=ATTEMPT,
        binder=ScriptedBinder(backend, extra_profiles=extra_profiles),
        agent_invocation_limit=limit,
        evidence_store=store,
        deadline_monotonic=deadline_monotonic,
        invoke_timeout_seconds=invoke_timeout_seconds,
        # Hermetic by default: only the offline case reads the real env gate.
        offline_env=offline_env,
    )
    return service, backend


def _open(service: ParentAgentService, profile_id: str = "solver") -> str:
    opened = service.open_session(profile_id=profile_id)
    assert opened["ok"], opened
    return str(opened["session_id"])


def test_invoke_forwards_tools_and_returns_tool_calls(tmp_path: Path) -> None:
    backend = ScriptedExecutor(
        tool_calls=({"id": "call_1", "name": "lookup", "arguments": {"q": "a"}},)
    )
    service, _ = _service(tmp_path, executor=backend)
    catalog = [{"type": "function", "function": {"name": "lookup"}}]
    history = [{"role": "user", "content": "need lookup"}]

    answer = service.invoke(
        session_id=_open(service),
        prompt="need lookup",
        tools=catalog,
        messages=history,
    )

    assert answer["ok"] is True
    assert answer["tool_calls"] == [
        {"id": "call_1", "name": "lookup", "arguments": {"q": "a"}},
    ]
    assert backend.tools == [catalog]
    assert backend.messages == [history]


def test_record_observation_appends_after_seal(tmp_path: Path) -> None:
    backend = ScriptedExecutor(
        tool_calls=({"id": "call_1", "name": "lookup", "arguments": {"q": "a"}},)
    )
    service, _ = _service(tmp_path, executor=backend)
    session = _open(service)
    answer = service.invoke(session_id=session, prompt="need lookup")
    observed = service.record_observation(
        session_id=session,
        tool_call_id="call_1",
        content='{"ok": true}',
        invocation_id=str(answer["invocation_id"]),
        function_name="lookup",
        raw_output={"ok": True},
    )
    assert observed["ok"] is True
    assert service.evidence_store is not None
    dirs = service.evidence_store.list_invocations()
    assert len(dirs) == 1
    events = [
        json.loads(line)
        for line in (dirs[0] / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    update = next(ev for ev in events if ev.get("phase") == "update")
    assert update["kind"] == "tool"
    assert update["tool_call_id"] == "call_1"
    assert update["content"] == '{"ok": true}'
    assert update["raw_output"] == {"ok": True}
    assert update["source"] == "ageval"
    meta = json.loads((dirs[0] / "metadata.json").read_text(encoding="utf-8"))
    assert meta["event_count"] == len(events)


def test_session_invokes_carry_turns_and_evidence(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    session = _open(service)

    first = service.invoke(session_id=session, prompt="one")
    second = service.invoke(session_id=session, prompt="two")

    assert [first["ok"], second["ok"]] == [True, True]
    assert second["structured"] == {"answer": 42, "turn": 2}
    assert backend.prompts == ["one", "two"]
    assert first["provider_session_handle"] is None
    assert service.invocations_completed == 2
    assert service.evidence_store is not None
    assert len(service.evidence_store.list_invocations()) == 2


def test_seal_run_refuses_solver_and_keeps_judge_on_evaluate_surface(
    tmp_path: Path,
) -> None:
    service, backend = _service(tmp_path, extra_profiles=("judge",))
    solver = _open(service, "solver")
    assert service.invoke(session_id=solver, prompt="solve")["ok"] is True
    assert service.evidence_store is not None
    assert len(service.evidence_store.list_invocations()) == 1
    assert service.evidence_store.list_evaluation_invocations() == []

    service.seal_run()
    refused = service.open_session(profile_id="solver")
    assert refused["error"] == "solver_writers_stopped"
    closed = service.invoke(session_id=solver, prompt="after-gold")
    assert closed["error"] == "session_closed"
    assert backend.prompts == ["solve"]

    judge = _open(service, "judge")
    answer = service.invoke(session_id=judge, prompt="GOLD BODY must not be layer C user")
    assert answer["ok"] is True
    assert len(service.evidence_store.list_invocations()) == 1
    eval_dirs = service.evidence_store.list_evaluation_invocations()
    assert len(eval_dirs) == 1
    assert "evaluation/invocations/" in str(eval_dirs[0])


def test_open_session_unknown_evaluate_environment_fails_closed(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    service.evaluate_environment_names = frozenset({"audit"})
    called: list[str] = []
    service.evaluate_environment_binder = lambda name, profile_id=None: called.append(name)
    refused = service.open_session(profile_id="solver", environment="nope")
    assert refused["error"] == "unknown_evaluate_environment"
    assert called == []


def test_open_session_named_environment_refuses_before_evaluate(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, extra_profiles=("judge",))
    service.evaluate_environment_names = frozenset({"audit"})
    called: list[str] = []

    async def _bind(name: str, profile_id: str | None = None) -> str:
        called.append(name)
        del profile_id
        return name

    service.evaluate_environment_binder = _bind
    refused = service.open_session(profile_id="judge", environment="audit")
    assert refused["error"] == "unknown_evaluate_environment"
    assert called == []


def test_open_session_named_environment_runs_binder_before_bind(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, extra_profiles=("judge",))
    service.seal_run()
    service.evaluate_environment_names = frozenset({"audit"})
    called: list[tuple[str, str | None]] = []

    async def _bind(name: str, profile_id: str | None = None) -> str:
        called.append((name, profile_id))
        return name

    service.evaluate_environment_binder = _bind
    opened = service.open_session(profile_id="judge", environment="audit")
    assert opened["ok"] is True
    assert called == [("audit", "judge")]


def test_open_session_named_map_requires_environment_for_non_http(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, extra_profiles=("judge",))
    service.seal_run()
    service.evaluate_environment_names = frozenset({"audit"})
    called: list[str] = []
    service.evaluate_environment_binder = lambda name, profile_id=None: called.append(name)
    refused = service.open_session(profile_id="judge")
    assert refused["error"] == "unknown_evaluate_environment"
    assert called == []


def test_open_session_http_judge_ignores_environment_attach(tmp_path: Path) -> None:
    class HttpBinder(ScriptedBinder):
        def profile(self, profile_id: str) -> dict[str, object]:
            row = dict(super().profile(profile_id))
            row["executor"] = "openai-http"
            return row

    backend = ScriptedExecutor()
    service = ParentAgentService(
        attempt_id=ATTEMPT,
        binder=HttpBinder(backend, extra_profiles=("judge",)),
        agent_invocation_limit=2,
        evidence_store=AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="r"),
        offline_env="",
    )
    service.seal_run()
    service.evaluate_environment_names = frozenset({"audit"})
    called: list[str] = []
    service.evaluate_environment_binder = lambda name, profile_id=None: called.append(name)
    named = service.open_session(profile_id="judge", environment="audit")
    omitted = service.open_session(profile_id="judge")
    assert named["ok"] is True
    assert omitted["ok"] is True
    assert called == []


def test_open_session_inbox_exec_targets_named_host(tmp_path: Path) -> None:
    class InboxBinder(ScriptedBinder):
        def profile(self, profile_id: str) -> dict[str, object]:
            row = dict(super().profile(profile_id))
            row["executor"] = "dsh"
            return row

    backend = ScriptedExecutor()
    service = ParentAgentService(
        attempt_id=ATTEMPT,
        binder=InboxBinder(backend, extra_profiles=("judge",)),
        agent_invocation_limit=2,
        evidence_store=AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="r"),
        offline_env="",
    )
    service.seal_run()
    service.evaluate_environment_names = frozenset({"audit"})
    called: list[tuple[str, str | None]] = []

    async def _bind(name: str, profile_id: str | None = None) -> str:
        called.append((name, profile_id))
        return name

    service.evaluate_environment_binder = _bind
    opened = service.open_session(profile_id="judge", environment="audit")
    assert opened["ok"] is True
    assert called == [("audit", "judge")]


def test_unknown_profile_never_opens(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    assert service.open_session(profile_id="nobody") == {
        "ok": False,
        "error": "unknown_profile",
        "profile_id": "nobody",
    }


def test_invocation_ceiling_refuses_before_the_executor_runs(tmp_path: Path) -> None:
    service, backend = _service(tmp_path, limit=1)
    session = _open(service)

    assert service.invoke(session_id=session, prompt="one")["ok"] is True
    refused = service.invoke(session_id=session, prompt="two")

    assert refused == {"ok": False, "error": "agent_invocation_limit"}
    assert backend.prompts == ["one"], "the ceiling must hold before the effect"


def test_quota_refusal_records_agent_invocations(tmp_path: Path) -> None:
    service, backend = _service(tmp_path, limit=0)
    seen: list[str] = []
    service.on_limit_reached = seen.append
    session = _open(service)

    refused = service.invoke(session_id=session, prompt="one")

    assert refused["error"] == "agent_invocation_limit"
    assert seen == ["agent_invocations"]
    assert backend.prompts == []


def test_wall_refusal_records_wall_time_seconds(tmp_path: Path) -> None:
    service, backend = _service(tmp_path, deadline_monotonic=time.monotonic() - 1.0)
    seen: list[str] = []
    service.on_limit_reached = seen.append

    assert service.open_session(profile_id="solver")["error"] == "wall_time_exceeded"
    assert seen == ["wall_time_seconds"]
    assert backend.prompts == []


def test_sealed_judge_invoke_does_not_consume_the_run_quota(tmp_path: Path) -> None:
    service, backend = _service(tmp_path, limit=1, extra_profiles=("judge",))
    seen: list[str] = []
    service.on_limit_reached = seen.append
    assert service.invoke(session_id=_open(service), prompt="solve")["ok"] is True
    service.seal_run()
    service.deadline_monotonic = time.monotonic() + 30.0
    opened = service.open_session(profile_id="judge")
    assert opened["ok"] is True, opened

    answer = service.invoke(session_id=str(opened["session_id"]), prompt="score")

    assert answer["ok"] is True
    assert seen == []
    assert backend.prompts == ["solve", "score"]


def test_sealed_wall_refusal_does_not_record_a_run_limit(tmp_path: Path) -> None:
    service, _backend = _service(tmp_path, extra_profiles=("judge",))
    service.seal_run()
    service.deadline_monotonic = time.monotonic() - 1.0
    seen: list[str] = []
    service.on_limit_reached = seen.append

    refused = service.open_session(profile_id="judge")

    assert refused["error"] == "wall_time_exceeded"
    assert seen == []


def test_zero_quota_still_allows_an_evaluate_phase_invoke(tmp_path: Path) -> None:
    service, backend = _service(tmp_path, limit=0, extra_profiles=("judge",))
    service.seal_run()
    opened = service.open_session(profile_id="judge")
    assert opened["ok"] is True, opened

    assert service.invoke(session_id=str(opened["session_id"]), prompt="score")["ok"] is True
    assert backend.prompts == ["score"]


def test_expired_wall_deadline_refuses_before_the_executor_runs(tmp_path: Path) -> None:
    service, backend = _service(tmp_path, deadline_monotonic=time.monotonic() - 1.0)
    assert service.open_session(profile_id="solver")["error"] == "wall_time_exceeded"

    service.deadline_monotonic = None
    session = _open(service)
    service.deadline_monotonic = time.monotonic() - 1.0
    refused = service.invoke(session_id=session, prompt="one")

    assert refused["error"] == "wall_time_exceeded"
    assert backend.prompts == []


def test_remaining_wall_time_caps_the_invoke_timeout(tmp_path: Path) -> None:
    service, backend = _service(
        tmp_path,
        deadline_monotonic=time.monotonic() + 5.0,
        invoke_timeout_seconds=300.0,
    )
    service.invoke(session_id=_open(service), prompt="one")
    assert backend.timeouts[0] <= 5.0


def test_closed_session_refuses_and_closes_the_executor(tmp_path: Path) -> None:
    service, backend = _service(tmp_path)
    session = _open(service)

    assert service.close_session(session_id=session) == {"ok": True}
    assert backend.closed is True
    assert service.invoke(session_id=session, prompt="one")["error"] == "session_closed"
    assert service.invoke(session_id="sess_missing", prompt="one")["error"] == "unknown_session"


def test_executor_crash_is_sealed_as_evidence(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, executor=ScriptedExecutor(raises=RuntimeError("boom")))
    answer = service.invoke(session_id=_open(service), prompt="one")

    assert answer["ok"] is False
    assert answer["error"] == "RuntimeError"
    assert service.evidence_store is not None
    (directory,) = service.evidence_store.list_invocations()
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "crash"
    assert metadata["error"] == "RuntimeError"
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    crash = next(event for event in events if event.get("phase") == "crash")
    assert crash["error_type"] == "RuntimeError"
    assert crash["detail"] == "boom"
    assert not (directory / "final-response.json").exists()


def test_successful_invoke_does_not_download_workspace(tmp_path: Path) -> None:
    """Agent Service returns AgentResult only. No per-invoke workspace harvest."""

    class _Host:
        def __init__(self) -> None:
            self.downloads: list[tuple[object, object]] = []

        async def download(self, source: object, dest: object) -> None:
            self.downloads.append((source, dest))

    class _RemoteExecutor(ScriptedExecutor):
        def __init__(self) -> None:
            super().__init__()
            self._host = _Host()

    backend = _RemoteExecutor()
    service, _ = _service(tmp_path, executor=backend)
    answer = service.invoke(session_id=_open(service), prompt="one")

    assert answer["ok"] is True
    assert backend._host.downloads == []


def test_offline_gate_refuses_every_invoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_OFFLINE_AGENT", "1")
    service, backend = _service(tmp_path, offline_env="AGEVAL_OFFLINE_AGENT")
    session = _open(service)

    refused = service.invoke(session_id=session, prompt="one")

    assert refused["error"] == "offline_forced"
    assert backend.prompts == []


def test_socket_round_trip_gives_the_worker_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is the transport, not the offline gate: the client refuses first.
    monkeypatch.delenv("AGEVAL_OFFLINE_AGENT", raising=False)
    service, backend = _service(tmp_path)
    # A Unix socket name has ~100 usable bytes; pytest's tmp_path does not fit.
    server = AgentServiceServer(service, Path(tempfile.mkdtemp(prefix="ageval-")) / "agent.sock")
    server.start()
    try:
        opened = agent_service_client_call(
            str(server.socket_path),
            {"op": "open", "profile_id": "solver", "attempt_id": "ignored"},
        )
        assert opened["ok"] is True
        answer = agent_service_client_call(
            str(server.socket_path),
            {"op": "invoke", "session_id": opened["session_id"], "prompt": "one"},
        )
        assert answer["ok"] is True
        assert backend.prompts == ["one"]
        assert agent_service_client_call(
            str(server.socket_path),
            {"op": "nonsense"},
        ) == {"ok": False, "error": "unknown_op"}
    finally:
        server.stop()

    assert not server.socket_path.exists()
    assert backend.closed is True, "stopping the service must close open sessions"


def test_quota_never_refunds() -> None:
    quota = AgentInvocationQuota(limit=2)
    assert [quota.try_consume(), quota.try_consume(), quota.try_consume()] == [True, True, False]
    assert quota.remaining == 0
    assert AgentInvocationQuota(limit=-5).limit == 0


def test_task_declared_invoke_timeout_wins() -> None:
    assert resolve_invoke_timeout_seconds({"agent_timeout_seconds": 12.5}) == 12.5
    assert resolve_invoke_timeout_seconds({"agent_timeout_seconds": 0}) == (
        DEFAULT_INVOKE_TIMEOUT_SECONDS
    )
    assert resolve_invoke_timeout_seconds({}) == DEFAULT_INVOKE_TIMEOUT_SECONDS
    assert resolve_invoke_timeout_seconds(None) == DEFAULT_INVOKE_TIMEOUT_SECONDS
