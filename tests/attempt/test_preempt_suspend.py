"""Preempt leaves the Attempt unsealed and does not tear the box down."""

from __future__ import annotations

from typing import Any

import pytest

from ageval.attempt import run_attempt
from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import environment, run
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import ACTIVITY_LOG_REL, AttemptEvidenceStore
from ageval.plugins.defaults import register_defaults
from ageval.plugins.protocol import BindingIntent
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.runtime.cancellation import CancellationSignal
from ageval.runtime.preempt import AttemptSuspended, mark_attempt_preempted


def _ctx(tmp_path: Any) -> AttemptCtx:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    return AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=None,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=object(),  # type: ignore[arg-type]
        evidence=store,
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
    )


class _Host:
    def __init__(self) -> None:
        self.stops: list[bool] = []

    async def stop(self, *, delete: bool) -> None:
        self.stops.append(delete)


@pytest.mark.asyncio
async def test_preempt_skips_record_and_does_not_stop_the_box(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    async def _environment(ctx: AttemptCtx) -> None:
        ctx.phase = "environment"
        order.append("environment")

    async def _run(ctx: AttemptCtx) -> None:
        ctx.phase = "run"
        order.append("run")
        ctx.suspended = True
        raise AttemptSuspended()

    monkeypatch.setattr(environment, "run", _environment)
    monkeypatch.setattr(run, "run", _run)
    ctx = _ctx(tmp_path)
    host = _Host()
    ctx.host = host  # type: ignore[assignment]
    await run_attempt(ctx)
    assert order == ["environment", "run"]
    assert "record" not in order
    assert host.stops == []
    assert ctx.suspended is True
    assert not any(fact.name == "phase_failed" for fact in ctx.phase_facts)
    assert not (tmp_path / "run" / "result.json").is_file()
    suspended = [fact for fact in ctx.phase_facts if fact.name == "environment_suspended"]
    assert suspended and suspended[0].detail["kept_running"] is True


@pytest.mark.asyncio
async def test_preempted_worker_envelope_does_not_seal(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _launch(ctx: AttemptCtx) -> dict[str, object]:
        del ctx
        return {"ok": True, "preempted": True}

    monkeypatch.setattr("ageval.runtime.task_launch.launch_task_worker", _launch)
    ctx = _ctx(tmp_path)
    with pytest.raises(AttemptSuspended):
        await run.run(ctx)
    assert ctx.suspended is True
    assert any(fact.name == "attempt_preempted" for fact in ctx.phase_facts)


def test_task_worker_no_result_is_not_preempt() -> None:
    from ageval.attempt.phases.run import _suspend_for_preempt

    ctx = _ctx_ns()
    assert _suspend_for_preempt(ctx, {"ok": False, "error": "task_worker_no_result"}) is False
    assert _suspend_for_preempt(ctx, {"ok": False, "error": "ValueError"}) is False
    assert _suspend_for_preempt(ctx, {"ok": True, "preempted": True}) is True


def _ctx_ns() -> AttemptCtx:
    return AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=type("Lock", (), {"task_id": "alpha"})(),  # type: ignore[arg-type]
        profile_id="solver",
        bindings=None,  # type: ignore[arg-type]
        registry=None,  # type: ignore[arg-type]
        services=None,  # type: ignore[arg-type]
        host=object(),  # type: ignore[arg-type]
        evidence=None,
        cancellation=CancellationSignal(),
        task_root=__import__("pathlib").Path("."),
        dataset_root=__import__("pathlib").Path("."),
        suite_run_id="suite",
    )


def test_mark_preempt_aborts_the_open_turn_and_checkpoints(tmp_path: Any) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    log = ActivityLog.open(store.root / ACTIVITY_LOG_REL)
    log.append(
        request_id="mt_req_inv_0",
        kind="model_turn",
        status="in_flight",
        payload={
            "session_id": "sess",
            "invoke_request_id": "req_inv",
            "step_index": 0,
            "delta_messages": [],
            "system_section_deltas": {},
        },
    )
    log.append(
        request_id="req_inv",
        kind="invoke",
        status="in_flight",
        payload={
            "session_id": "sess",
            "turn_index": 1,
            "prompt": "go",
            "tools_digest": None,
            "messages_digest": None,
            "explicit_messages": None,
        },
    )
    ctx = _ctx(tmp_path)
    ctx.evidence = store
    ctx.activity = log
    mark_attempt_preempted(ctx)
    assert log.latest_status(kind="model_turn", request_id="mt_req_inv_0") == "aborted"
    assert log.latest_status(kind="invoke", request_id="req_inv") == "in_flight"
    assert log.has_completed_phase("preempted")
    assert (store.root / "checkpoints").is_dir()
    assert not (store.root / "result.json").is_file()
