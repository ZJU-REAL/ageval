"""Resume skips run only after seal_run and the declared artifact snapshot."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.attempt import run_attempt
from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import cleanup, environment, evaluate, record, run
from ageval.evidence.activity import ActivityLog
from ageval.evidence.store import TASK_ARTIFACTS_REL, AttemptEvidenceStore
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.runtime.cancellation import CancellationSignal


def _ctx(tmp_path: Path, log: ActivityLog, artifacts: list[dict[str, str]] | None) -> AttemptCtx:
    evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    lock = SimpleNamespace(resolved_references={"artifacts": artifacts or []})
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=lock,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=ExtensionGraph(profile_id="solver"),
        registry=ExtensionRegistry(),
        services=ServiceTable(),
        host=object(),  # type: ignore[arg-type]
        evidence=evidence,
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        activity=log,
    )
    ctx.recovery_attached = True
    return ctx


def _log(tmp_path: Path, *, seal: bool) -> ActivityLog:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    done = {
        "elapsed_ms": 1.0,
        "limit_reached": None,
        "checkpoint_seq": None,
    }
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
        payload={"phase": "environment", **done},
    )
    if seal:
        log.append(
            request_id="phase_seal_run",
            kind="phase",
            status="completed",
            payload={"phase": "seal_run", **done},
        )
    return log


def _patch(monkeypatch: pytest.MonkeyPatch, order: list[str]) -> None:
    async def _phase(name: str, ctx: AttemptCtx) -> None:
        ctx.phase = name
        order.append(name)

    monkeypatch.setattr(environment, "run", lambda ctx: _phase("environment", ctx))
    monkeypatch.setattr(run, "run", lambda ctx: _phase("run", ctx))
    monkeypatch.setattr(evaluate, "run", lambda ctx: _phase("evaluate", ctx))
    monkeypatch.setattr(record, "run", lambda ctx: _phase("record", ctx))
    monkeypatch.setattr(cleanup, "run", lambda ctx: _phase("cleanup", ctx))


def _artifact_lock() -> list[dict[str, str]]:
    return [{"id": "answer", "path": "answer.json", "kind": "file"}]


@pytest.mark.asyncio
async def test_sealed_run_with_missing_artifact_reenters_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    _patch(monkeypatch, order)
    ctx = _ctx(tmp_path, _log(tmp_path, seal=True), _artifact_lock())
    await run_attempt(ctx)
    assert order[0] == "run"
    assert "evaluate" in order


@pytest.mark.asyncio
async def test_sealed_run_with_artifacts_skips_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    _patch(monkeypatch, order)
    ctx = _ctx(tmp_path, _log(tmp_path, seal=True), _artifact_lock())
    staged = ctx.evidence.path(TASK_ARTIFACTS_REL)
    staged.mkdir(parents=True)
    (staged / "answer.json").write_text('{"ok": true}\n', encoding="utf-8")
    await run_attempt(ctx)
    assert "run" not in order
    assert order[0] == "evaluate"


@pytest.mark.asyncio
async def test_sealed_run_without_publishable_artifacts_skips_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    _patch(monkeypatch, order)
    ctx = _ctx(tmp_path, _log(tmp_path, seal=True), [])
    await run_attempt(ctx)
    assert "run" not in order
    assert order[0] == "evaluate"


@pytest.mark.asyncio
async def test_harvest_failure_does_not_complete_seal_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    ctx = _ctx(tmp_path, log, [])
    ctx.recovery_attached = False

    async def _boom(_ctx: object) -> None:
        raise _HarvestBroke

    monkeypatch.setattr(run, "harvest_workspace_artifacts", _boom)

    async def _worker(_ctx: object) -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(run, "_run_task_entry", _worker)
    with pytest.raises(_HarvestBroke):
        await run.run(ctx)
    assert log.has_completed_phase("seal_run") is False
    assert ctx._writers_stopped is True


@pytest.mark.asyncio
async def test_seal_run_is_written_after_harvest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    ctx = _ctx(tmp_path, log, [])
    seen: list[bool] = []

    async def _harvest(inner: AttemptCtx) -> None:
        seen.append(inner.activity.has_completed_phase("seal_run"))

    async def _worker(_ctx: object) -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(run, "harvest_workspace_artifacts", _harvest)
    monkeypatch.setattr(run, "_run_task_entry", _worker)
    monkeypatch.setattr(run, "emit", lambda *_args, **_kwargs: _async_none())
    await run.run(ctx)
    assert seen == [False]
    assert log.has_completed_phase("seal_run") is True


class _HarvestBroke(RuntimeError):
    """Stand-in harvest failure. The message stays on the class."""


async def _async_none() -> None:
    return None
