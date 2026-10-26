"""Recovered run-phase wall time comes from logged step clocks, not a fresh budget."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import run as run_phase
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.runtime.cancellation import CancellationSignal


def _log(tmp_path: Path, elapsed_ms: float) -> ActivityLog:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    log.append(
        request_id="phase_run",
        kind="phase",
        status="in_flight",
        payload={"phase": "run"},
    )
    log.append(
        request_id="tool_sess_call_1",
        kind="tool_call",
        status="completed",
        payload={
            "session_id": "sess",
            "invoke_request_id": "req_1",
            "tool_call_id": "call_1",
            "outcome": "ok",
            "exit_code": 0,
            "content": "ok",
            "stderr": None,
            "raw_output": None,
            "checkpoint_seq": None,
            "elapsed_ms": elapsed_ms,
        },
    )
    return log


def _ctx(tmp_path: Path, log: ActivityLog, *, wall_time_seconds: int) -> AttemptCtx:
    return AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=SimpleNamespace(limits={"wall_time_seconds": wall_time_seconds}),  # type: ignore[arg-type]
        profile_id="solver",
        bindings=ExtensionGraph(profile_id="solver"),
        registry=ExtensionRegistry(),
        services=ServiceTable(),
        host=object(),  # type: ignore[arg-type]
        evidence=AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r"),
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )


def test_arm_phase_budget_keeps_about_five_seconds(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _log(tmp_path, 25000.0), wall_time_seconds=30)
    ctx.arm_phase_budget("wall_time_seconds")
    remaining = ctx.remaining_seconds()
    assert remaining is not None
    assert 4.0 < remaining <= 5.0


@pytest.mark.asyncio
async def test_exhausted_recovered_wall_does_not_start_the_solver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, _log(tmp_path, 40000.0), wall_time_seconds=30)
    started: list[str] = []

    async def _worker(_ctx: object) -> dict[str, object]:
        started.append("run.py")
        return {"ok": True}

    monkeypatch.setattr(run_phase, "_run_task_entry", _worker)
    await run_phase.run(ctx)
    assert started == []
    assert ctx.phase_budget_exhausted() is True
    assert ctx.limit_name() == "wall_time_seconds"
