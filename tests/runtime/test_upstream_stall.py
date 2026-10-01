"""A non-ok executor invoke stalls inside the parent until the time budget."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.helpers.agent_binding import ScriptedBinder, ScriptedExecutor

from ageval.attempt.ctx import AttemptCtx
from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.protocol import ExtensionGraph, HandlerRef
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import AFTER_AGENT_INVOKE, BEFORE_AGENT_INVOKE
from ageval.runtime.cancellation import CancellationSignal
from ageval.runtime.parent_agent import ParentAgentService
from ageval.runtime.upstream_stall import current_stall

ATTEMPT = "attempt_" + "a" * 16


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _result(*, ok: bool, error: str | None = None, repeatable: bool = True) -> AgentResult:
    return AgentResult(
        model="scripted-model",
        text="ok" if ok else "",
        structured={"answer": 1} if ok else None,
        ok=ok,
        error=error,
        repeatable=repeatable,
    )


def _service(
    tmp_path: Path,
    executor: Any,
    *,
    limit: int = 2,
    options: dict[str, object] | None = None,
    invoke_timeout_seconds: float = 30.0,
) -> tuple[ParentAgentService, _Clock, list[dict[str, object]], list[str], list[tuple[str, dict]]]:
    clock = _Clock()
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id=ATTEMPT, run_id="run_x")
    service = ParentAgentService(
        attempt_id=ATTEMPT,
        binder=ScriptedBinder(executor, options=options),
        agent_invocation_limit=limit,
        evidence_store=store,
        invoke_timeout_seconds=invoke_timeout_seconds,
        offline_env="",
        _monotonic=clock.monotonic,
        _sleep=clock.sleep,
    )
    service.task_id = "alpha"
    service._now = lambda: datetime(2026, 10, 1, tzinfo=UTC)
    events: list[dict[str, object]] = []
    labels: list[str] = []
    facts: list[tuple[str, dict]] = []
    service.on_progress = events.append
    service.on_phase = lambda _event, name: labels.append(name)
    service.record_stall_fact = lambda name, detail: facts.append((name, dict(detail)))
    return service, clock, events, labels, facts


def _open(service: ParentAgentService) -> str:
    opened = service.open_session(profile_id="solver")
    assert opened["ok"], opened
    return str(opened["session_id"])


def test_http_error_retries_then_returns_the_success(tmp_path: Path) -> None:
    backend = ScriptedExecutor(
        script=[
            _result(ok=False, error="HTTPError:401"),
            _result(ok=False, error="HTTPError:401"),
            _result(ok=True),
        ]
    )
    service, clock, events, labels, facts = _service(tmp_path, backend)
    catalog = [{"type": "function", "function": {"name": "lookup"}}]
    history = [{"role": "user", "content": "same"}]

    answer = service.invoke(
        session_id=_open(service),
        prompt="same",
        tools=catalog,
        messages=history,
    )

    assert answer["ok"] is True
    assert answer["error"] is None
    assert backend.prompts == ["same", "same", "same"]
    assert backend.tools == [catalog, catalog, catalog]
    assert backend.messages == [history, history, history]
    assert clock.sleeps == [60.0, 60.0]
    assert service.invocations_completed == 1
    assert service.invoke_quota is not None
    assert service.invoke_quota.remaining == 1
    assert service.evidence_store is not None
    assert len(service.evidence_store.list_invocations()) == 1
    assert [event["type"] for event in events] == ["upstream_stall"] * 4
    assert [event["outcome"] for event in events] == ["started", "wait", "wait", "resumed"]
    assert [event["state"] for event in events] == ["upstream_stall"] * 4
    assert events[0]["seconds_until_next"] == 60
    assert events[0]["remaining_budget"] == 3600
    assert events[2]["remaining_budget"] == 3540
    assert events[-1]["phase"] == "run"
    assert labels[0] == "upstream_stall"
    assert labels[-1] == "run"
    assert facts == [
        (
            "upstream_stall",
            {
                "reason": "HTTPError:401",
                "started_at": "2026-10-01T00:00:00Z",
                "try_count": 3,
                "outcome": "resumed",
            },
        )
    ]


def test_stall_does_not_spend_the_phase_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGEVAL_AGENT_INVOKE_TIMEOUT", raising=False)
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=None,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=ExtensionGraph(profile_id="solver"),
        registry=ExtensionRegistry(),
        services=ServiceTable(),
        host=object(),  # type: ignore[arg-type]
        evidence=AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r"),
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
    )
    ctx.deadline_monotonic = time.monotonic() + 100.0

    class _Probe:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.timeouts: list[float] = []
            self.remaining: float | None = None

        def invoke(self, prompt: str, *, timeout: float = 60.0, **_kwargs: object) -> AgentResult:
            self.prompts.append(prompt)
            self.timeouts.append(timeout)
            if len(self.prompts) == 1:
                return _result(ok=False, error="HTTPError:401")
            self.remaining = ctx.remaining_seconds()
            return _result(ok=True)

    backend = _Probe()
    service, clock, _events, labels, _facts = _service(
        tmp_path, backend, invoke_timeout_seconds=30.0
    )
    ctx.agent_service = service
    service.deadline_monotonic = ctx.deadline_monotonic
    service.on_phase_clock = lambda frozen: (
        ctx.freeze_phase_clock() if frozen else ctx.thaw_phase_clock()
    )

    def _sleep(seconds: float) -> None:
        clock.sleep(seconds)
        ctx.deadline_monotonic = time.monotonic() - 5

    service._sleep = _sleep
    answer = service.invoke(session_id=_open(service), prompt="again")

    assert answer["ok"] is True
    assert labels[0] == "upstream_stall"
    assert labels[-1] == "run"
    assert backend.timeouts[1] == pytest.approx(30.0)
    assert backend.remaining is not None and backend.remaining > 50
    assert ctx.phase_budget_exhausted() is False
    left = ctx.remaining_seconds()
    assert left is not None and left > 50
    assert service.deadline_monotonic is not None
    assert service.deadline_monotonic > time.monotonic()


def test_zero_budget_fails_on_the_first_error_without_a_label(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="HTTPError:401")])
    service, clock, events, labels, facts = _service(
        tmp_path, backend, options={"upstream_stall_seconds": 0}
    )

    answer = service.invoke(session_id=_open(service), prompt="once")

    assert answer["ok"] is False
    assert answer["error"] == "HTTPError:401"
    assert backend.prompts == ["once"]
    assert clock.sleeps == []
    assert events == []
    assert labels == []
    assert facts == []
    assert service.invocations_completed == 1


def test_budget_shorter_than_one_interval_ends_without_sleep(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="HTTPError:503")])
    service, clock, events, _labels, facts = _service(
        tmp_path, backend, options={"upstream_stall_seconds": 30}
    )

    answer = service.invoke(session_id=_open(service), prompt="short")

    assert answer["ok"] is False
    assert answer["error"] == "HTTPError:503"
    assert backend.prompts == ["short"]
    assert clock.sleeps == []
    assert [event["outcome"] for event in events] == ["started", "budget_exhausted"]
    assert facts[0][1]["outcome"] == "budget_exhausted"
    assert facts[0][1]["try_count"] == 1
    assert facts[0][1]["reason"] == "HTTPError:503"


def test_not_repeatable_emits_one_event_and_does_not_sleep(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="acp_timeout", repeatable=False)])
    service, clock, events, labels, facts = _service(tmp_path, backend)

    answer = service.invoke(session_id=_open(service), prompt="edited")

    assert answer["ok"] is False
    assert answer["error"] == "acp_timeout"
    assert backend.prompts == ["edited"]
    assert clock.sleeps == []
    assert [event["outcome"] for event in events] == ["not_repeatable"]
    assert events[0]["seconds_until_next"] == 0
    assert labels == ["run"]
    assert facts[0][1]["outcome"] == "not_repeatable"
    assert facts[0][1]["try_count"] == 1


def test_later_not_repeatable_closes_the_open_stall(tmp_path: Path) -> None:
    backend = ScriptedExecutor(
        script=[
            _result(ok=False, error="HTTPError:503"),
            _result(ok=False, error="acp_timeout", repeatable=False),
        ]
    )
    service, clock, events, labels, facts = _service(tmp_path, backend)

    answer = service.invoke(session_id=_open(service), prompt="edited")

    assert answer["ok"] is False
    assert answer["error"] == "acp_timeout"
    assert backend.prompts == ["edited", "edited"]
    assert clock.sleeps == [60.0]
    assert [event["outcome"] for event in events] == ["started", "wait", "not_repeatable"]
    assert labels == ["upstream_stall", "upstream_stall", "run"]
    assert facts[0][1]["outcome"] == "not_repeatable"
    assert facts[0][1]["try_count"] == 2
    assert facts[0][1]["reason"] == "acp_timeout"


def test_zero_budget_hides_not_repeatable(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="acp_timeout", repeatable=False)])
    service, clock, events, labels, facts = _service(
        tmp_path, backend, options={"upstream_stall_seconds": 0}
    )

    answer = service.invoke(session_id=_open(service), prompt="edited")

    assert answer["ok"] is False
    assert backend.prompts == ["edited"]
    assert clock.sleeps == []
    assert events == []
    assert labels == []
    assert facts == []


def test_judge_stall_uses_the_evaluate_label_and_skips_the_run_quota(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="HTTPError:429"), _result(ok=True)])
    service, _clock, events, labels, _facts = _service(tmp_path, backend, limit=1)
    service._run_sealed = True

    answer = service.invoke(session_id=_open(service), prompt="judge")

    assert answer["ok"] is True
    assert service.invoke_quota is not None
    assert service.invoke_quota.remaining == 1
    assert events[0]["phase"] == "evaluate"
    assert labels[0] == "upstream_stall"
    assert labels[-1] == "evaluate"


def test_exhausted_wall_and_quota_do_not_enter_the_stall(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="HTTPError:401")])
    service, clock, events, labels, facts = _service(tmp_path, backend, limit=0)
    session = _open(service)

    quota = service.invoke(session_id=session, prompt="quota")
    assert quota["error"] == "agent_invocation_limit"
    assert backend.prompts == []

    service.agent_invocation_limit = 2
    assert service.invoke_quota is not None
    service.invoke_quota.limit = 2
    service.deadline_monotonic = time.monotonic() - 1
    wall = service.invoke(session_id=session, prompt="wall")

    assert wall["error"] == "wall_time_exceeded"
    assert backend.prompts == []
    assert clock.sleeps == []
    assert events == []
    assert labels == []
    assert facts == []


def test_offline_refusal_does_not_enter_the_stall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="HTTPError:401")])
    service, _clock, events, _labels, _facts = _service(tmp_path, backend)
    service.offline_env = "AGEVAL_STALL_OFFLINE_TEST"
    monkeypatch.setenv("AGEVAL_STALL_OFFLINE_TEST", "1")

    answer = service.invoke(session_id=_open(service), prompt="offline")

    assert answer["error"] == "offline_forced"
    assert backend.prompts == []
    assert events == []


def test_claimed_and_stall_exhausted_do_not_start_another_invoke(tmp_path: Path) -> None:
    class _Claim:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def invoke(self, prompt: str, **_kwargs: object) -> AgentResult:
            self.prompts.append(prompt)
            stall = current_stall()
            assert stall is not None
            stall.claim()
            return _result(ok=False, error="LimitsExceeded")

    claimed = _Claim()
    service, clock, events, _labels, _facts = _service(tmp_path, claimed)
    answer = service.invoke(session_id=_open(service), prompt="kept")
    assert answer["error"] == "LimitsExceeded"
    assert claimed.prompts == ["kept"]
    assert clock.sleeps == []
    assert events == []

    exhausted = ScriptedExecutor(script=[_result(ok=False, error="stall_exhausted")])
    service, clock, events, _labels, _facts = _service(tmp_path, exhausted)
    answer = service.invoke(session_id=_open(service), prompt="spent")
    assert answer["error"] == "stall_exhausted"
    assert exhausted.prompts == ["spent"]
    assert clock.sleeps == []
    assert events == []


def test_chains_run_once_around_the_retry(tmp_path: Path) -> None:
    backend = ScriptedExecutor(script=[_result(ok=False, error="HTTPError:401"), _result(ok=True)])
    service, _clock, _events, _labels, _facts = _service(tmp_path, backend)
    session = _open(service)
    graph = service.session_graph(session)
    assert graph is not None
    counts = {"before": 0, "after": 0}

    def _before(_ctx: object, value: object, nxt: object) -> object:
        counts["before"] += 1
        assert callable(nxt)
        return nxt(f"{value}!")

    def _after(_ctx: object, value: object, nxt: object) -> object:
        counts["after"] += 1
        assert callable(nxt)
        return nxt(value)

    graph.chains[BEFORE_AGENT_INVOKE] = [
        HandlerRef(
            plugin_id="t", handler=_before, priority=0, source="test", slot=BEFORE_AGENT_INVOKE
        )
    ]
    graph.chains[AFTER_AGENT_INVOKE] = [
        HandlerRef(
            plugin_id="t", handler=_after, priority=0, source="test", slot=AFTER_AGENT_INVOKE
        )
    ]

    answer = service.invoke(session_id=session, prompt="go")

    assert answer["ok"] is True
    assert counts == {"before": 1, "after": 1}
    assert backend.prompts == ["go!", "go!"]


def test_http_result_is_repeatable_unless_marked() -> None:
    failed = AgentResult(model="m", text="", structured=None, ok=False, error="HTTPError:401")
    assert failed.repeatable is True
