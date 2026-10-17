"""A sealed trajectory is checked before cleanup. Null usage fails the seal."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ageval.attempt import run_attempt
from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import cleanup, environment, evaluate, record, run
from ageval.evidence.invariants import (
    SealInvariantError,
    assert_sealed_invariants,
    usage_document_ok,
)
from ageval.evidence.store import AttemptEvidenceStore
from ageval.evidence.trajectory import TRAJECTORY_FILENAME
from ageval.plugins.defaults import register_defaults
from ageval.plugins.protocol import BindingIntent
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import SUMMARY_ENRICH
from ageval.runtime.cancellation import CancellationSignal


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


def test_usage_document_accepts_a_reason_and_rejects_null() -> None:
    assert usage_document_ok({"unavailable": "lost_on_timeout"})
    assert usage_document_ok({"unavailable": "not_reported"})
    assert usage_document_ok({"unavailable": "partial", "prompt_tokens": 4})
    assert usage_document_ok({"prompt_tokens": 0})
    assert usage_document_ok(None) is False
    assert usage_document_ok({}) is False
    assert usage_document_ok({"unavailable": "cancelled"}) is False


def test_null_terminal_usage_fails_the_invariant(tmp_path: Any) -> None:
    root = tmp_path / "run"
    root.mkdir()
    (root / TRAJECTORY_FILENAME).write_text(
        json.dumps({"type": "terminal", "usage": None}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SealInvariantError, match="not sealed"):
        assert_sealed_invariants(root, keep_vendor_raw=False)


def test_vendor_raw_left_behind_fails_only_after_slim(tmp_path: Any) -> None:
    root = tmp_path / "run"
    (root / "agent").mkdir(parents=True)
    (root / TRAJECTORY_FILENAME).write_text(
        json.dumps({"type": "terminal", "usage": {"unavailable": "not_reported"}}) + "\n",
        encoding="utf-8",
    )
    (root / "agent" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SealInvariantError, match="vendor raw"):
        assert_sealed_invariants(root, keep_vendor_raw=False)
    assert_sealed_invariants(root, keep_vendor_raw=True)


@pytest.mark.asyncio
async def test_evaluate_error_seals_before_cleanup(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    async def ok(name: str, ctx: AttemptCtx) -> None:
        ctx.phase = name
        order.append(name)

    async def boom(ctx: AttemptCtx) -> None:
        ctx.phase = "evaluate"
        order.append("evaluate")
        raise RuntimeError("eval_boom")

    real_cleanup = cleanup.run

    async def wrapped_cleanup(ctx: AttemptCtx) -> None:
        order.append("cleanup")
        await real_cleanup(ctx)

    monkeypatch.setattr(environment, "run", lambda ctx: ok("environment", ctx))
    monkeypatch.setattr(run, "run", lambda ctx: ok("run", ctx))
    monkeypatch.setattr(evaluate, "run", boom)
    monkeypatch.setattr(cleanup, "run", wrapped_cleanup)
    ctx = _ctx(tmp_path)
    await run_attempt(ctx)
    assert order == ["environment", "run", "evaluate", "cleanup"]
    assert (ctx.evidence.root / TRAJECTORY_FILENAME).is_file()
    assert_sealed_invariants(ctx.evidence.root, keep_vendor_raw=False)
    failed = [fact for fact in ctx.phase_facts if fact.name == "phase_failed"]
    assert len(failed) == 1
    assert failed[0].detail["phase"] == "evaluate"
    assert not any(fact.name == "seal_invariant_failed" for fact in ctx.phase_facts)


@pytest.mark.asyncio
async def test_record_continues_after_a_seal_step_failure(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ageval.plugins.defaults.trajectory_seal import DefaultTrajectorySeal

    calls: list[str] = []

    async def tracking_emit(ctx: AttemptCtx, slot: str, payload: object) -> dict[str, object]:
        del ctx, payload
        calls.append(slot)
        return {}

    def boom(self: DefaultTrajectorySeal, ctx: AttemptCtx, turns: list[object]) -> None:
        del self, ctx, turns
        raise RuntimeError("seal_boom")

    monkeypatch.setattr(record, "emit", tracking_emit)
    monkeypatch.setattr(DefaultTrajectorySeal, "seal", boom)
    ctx = _ctx(tmp_path)
    with pytest.raises(RuntimeError, match="record step failed: RuntimeError: seal_boom"):
        await record.run(ctx)
    assert SUMMARY_ENRICH in calls
    steps = [fact.detail["step"] for fact in ctx.phase_facts if fact.name == "record_step_failed"]
    assert steps == ["seal"]
