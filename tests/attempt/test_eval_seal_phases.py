"""Evaluate/record phases bind exclusive winners; PASS still only via bind_evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import evaluate, record
from ageval.environments.protocol import EVALUATION_PATH
from ageval.evidence.invariants import assert_sealed_invariants
from ageval.evidence.store import AttemptEvidenceStore
from ageval.plugins.defaults import register_defaults
from ageval.plugins.protocol import BindingIntent, ExplicitBinding, HandlerRef
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import (
    AFTER_EVALUATE,
    EVALUATION_RUNTIME,
    SUMMARY_ENRICH,
    TRAJECTORY_COLLECT,
    TRAJECTORY_SEAL,
)
from ageval.runtime.cancellation import CancellationSignal


class RecordingHost:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []

    async def upload(self, source: Path, dest: str) -> None:
        self.uploads.append((Path(source), str(dest)))


class RawPassRuntime:
    async def evaluate(self, ctx: Any) -> dict[str, Any]:
        del ctx
        return {"status": "PASS", "score": 1}


class ProbeSeal:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def seal(self, ctx: Any, turns: list[list[dict[str, Any]]]) -> Path:
        self.order.append("seal")
        path = ctx.evidence.root / "trajectory.jsonl"
        path.write_text(f'{{"turns": {len(turns)}, "probe": true}}\n', encoding="utf-8")
        return path


def _registry_with_runtime() -> ExtensionRegistry:
    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(
        EVALUATION_RUNTIME,
        "probe",
        lambda **_kwargs: RawPassRuntime(),
        source="test",
        is_factory=True,
    )
    return registry


def _ctx(
    tmp_path: Path,
    *,
    registry: ExtensionRegistry,
    graph: Any,
    host: Any | None = None,
    evaluation_src: Path | None = None,
) -> AttemptCtx:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=None,  # type: ignore[arg-type]
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=host or RecordingHost(),  # type: ignore[arg-type]
        evidence=store,
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
        evaluation_src=evaluation_src,
    )
    ctx.mark_writers_stopped()
    return ctx


@pytest.mark.asyncio
async def test_runtime_return_is_not_a_bound_pass(tmp_path: Path) -> None:
    registry = _registry_with_runtime()
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="probe")],
        ),
        registry,
    )
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    ctx.phase = "evaluate"
    raw = await RawPassRuntime().evaluate(ctx)
    assert raw["status"] == "PASS"
    assert ctx.evaluation_result is None


@pytest.mark.asyncio
async def test_evaluate_phase_binds_winner_raw_and_uploads_gold(tmp_path: Path) -> None:
    gold = tmp_path / "evaluation"
    gold.mkdir()
    (gold / "expected.txt").write_text("ok\n", encoding="utf-8")
    registry = _registry_with_runtime()
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="probe")],
        ),
        registry,
    )
    host = RecordingHost()
    ctx = _ctx(tmp_path, registry=registry, graph=graph, host=host, evaluation_src=gold)
    await evaluate.run(ctx)
    assert ctx.evaluation_result == {"status": "PASS", "score": 1}
    assert ctx.services.owner(EVALUATION_RUNTIME) == "probe"
    assert any(dest == EVALUATION_PATH for _src, dest in host.uploads)
    assert any(f.name == "gold_materialized" and f.phase == "evaluate" for f in ctx.phase_facts)


@pytest.mark.asyncio
async def test_after_evaluate_cannot_change_status(tmp_path: Path) -> None:
    async def flip_status(ctx: Any, value: Any, nxt: Any) -> Any:
        del ctx
        out = await nxt(value)
        return {**out, "status": "FAIL"}

    registry = _registry_with_runtime()
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="probe")],
        ),
        registry,
    )
    graph.chains[AFTER_EVALUATE] = [
        HandlerRef(plugin_id="probe", handler=flip_status, priority=1, source="test")
    ]
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    with pytest.raises(RuntimeError, match="after_evaluate must not change"):
        await evaluate.run(ctx)
    assert ctx.evaluation_result == {"status": "PASS", "score": 1}


@pytest.mark.asyncio
async def test_seal_winner_writes_after_collect(tmp_path: Path) -> None:
    order: list[str] = []

    async def collect(ctx: Any, value: Any, nxt: Any) -> Any:
        del ctx
        order.append("collect")
        return await nxt(value)

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(
        TRAJECTORY_SEAL,
        "probe-seal",
        lambda **_kwargs: ProbeSeal(order),
        source="test",
        is_factory=True,
    )
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=TRAJECTORY_SEAL, plugin="probe-seal")],
        ),
        registry,
    )
    graph.chains[TRAJECTORY_COLLECT] = [
        HandlerRef(plugin_id="probe", handler=collect, priority=1, source="test")
    ]
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    inv = ctx.evidence.root / "agent" / "invocations" / "001"
    inv.mkdir(parents=True)
    (inv / "metadata.json").write_text('{"seq": 1, "status": "completed"}', encoding="utf-8")
    (inv / "final-response.json").write_text('{"content": "hi"}', encoding="utf-8")
    (inv / "request.json").write_text('{"messages": [{"content": "go"}]}', encoding="utf-8")
    (inv / "events.jsonl").write_text("", encoding="utf-8")
    await record.run(ctx)
    assert order == ["collect", "seal"]
    text = (ctx.evidence.root / "trajectory.jsonl").read_text(encoding="utf-8")
    assert '"probe": true' in text
    assert ctx.services.owner(TRAJECTORY_SEAL) == "probe-seal"


@pytest.mark.asyncio
async def test_record_seals_evaluate_invokes_to_observation_not_trajectory(
    tmp_path: Path,
) -> None:
    import json

    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    agent = ctx.evidence.root / "agent" / "invocations" / "0001-solver"
    agent.mkdir(parents=True)
    (agent / "metadata.json").write_text(
        '{"seq": 1, "status": "completed", "profile_id": "solver"}',
        encoding="utf-8",
    )
    (agent / "final-response.json").write_text('{"content": "done"}', encoding="utf-8")
    (agent / "request.json").write_text(
        '{"messages": [{"content": "solve this"}]}',
        encoding="utf-8",
    )
    (agent / "events.jsonl").write_text("", encoding="utf-8")
    judge = ctx.evidence.root / "evaluation" / "invocations" / "0001-judge"
    judge.mkdir(parents=True)
    (judge / "metadata.json").write_text(
        '{"seq": 1, "status": "completed", "profile_id": "judge"}',
        encoding="utf-8",
    )
    (judge / "final-response.json").write_text('{"content": "1.0"}', encoding="utf-8")
    (judge / "request.json").write_text(
        '{"messages": [{"content": "hidden gold body"}]}',
        encoding="utf-8",
    )
    (judge / "events.jsonl").write_text("", encoding="utf-8")
    await record.run(ctx)
    traj = (ctx.evidence.root / "trajectory.jsonl").read_text(encoding="utf-8")
    obs = (ctx.evidence.root / "evaluation" / "observation.jsonl").read_text(encoding="utf-8")
    assert "solve this" in traj
    assert "hidden gold body" not in traj
    assert "hidden gold body" not in obs
    assert "1.0" in obs
    assert '"profile_id": "judge"' in obs
    assert not any(
        json.loads(line).get("role") == "user" for line in obs.splitlines() if line.strip()
    )


@pytest.mark.asyncio
async def test_record_preserves_sealed_rows_for_slimmed_invocations(tmp_path: Path) -> None:
    import json

    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    (ctx.evidence.root / "trajectory.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "turn",
                        "role": "user",
                        "content": "old prompt",
                        "turn_index": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "terminal",
                        "ok": True,
                        "usage": {"unavailable": "not_reported"},
                        "turn_index": 1,
                    }
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    (ctx.evidence.root / "agent" / "invocations" / "0001-slimmed").mkdir()
    fresh = ctx.evidence.root / "agent" / "invocations" / "0002-live"
    fresh.mkdir()
    (fresh / "metadata.json").write_text(
        '{"seq": 2, "status": "completed", "profile_id": "solver"}',
        encoding="utf-8",
    )
    (fresh / "final-response.json").write_text(
        '{"content": "done", "usage": {"unavailable": "not_reported"}}',
        encoding="utf-8",
    )
    (fresh / "request.json").write_text(
        '{"messages": [{"content": "new prompt"}]}',
        encoding="utf-8",
    )
    (fresh / "events.jsonl").write_text("", encoding="utf-8")

    await record.run(ctx)

    rows = [
        json.loads(line)
        for line in (ctx.evidence.root / "trajectory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["content"] for row in rows if row.get("role") == "user"] == [
        "old prompt",
        "new prompt",
    ]
    assert all(
        row.get("usage") == {"unavailable": "not_reported"}
        for row in rows
        if row.get("type") == "terminal"
    )
    assert_sealed_invariants(ctx.evidence.root, keep_vendor_raw=False)


@pytest.mark.asyncio
async def test_collect_usage_extra_lands_on_terminal(tmp_path: Path) -> None:
    import json

    async def collect(ctx: Any, value: Any, nxt: Any) -> Any:
        del ctx
        out = await nxt(value)
        if not isinstance(out, dict):
            return out
        extra = dict(out.get("extra") or {})
        extra["foo"] = True
        out["extra"] = extra
        return out

    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    graph.chains[TRAJECTORY_COLLECT] = [
        HandlerRef(plugin_id="probe", handler=collect, priority=1, source="test")
    ]
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    inv = ctx.evidence.root / "agent" / "invocations" / "001"
    inv.mkdir(parents=True)
    (inv / "metadata.json").write_text(
        '{"seq": 1, "status": "completed", "latency_ms": 88}',
        encoding="utf-8",
    )
    (inv / "final-response.json").write_text(
        '{"content": "hi", "usage": {"prompt_tokens": 3, "completion_tokens": 1}}',
        encoding="utf-8",
    )
    (inv / "request.json").write_text(
        '{"messages": [{"content": "go"}]}',
        encoding="utf-8",
    )
    (inv / "events.jsonl").write_text("", encoding="utf-8")
    await record.run(ctx)
    lines = [
        json.loads(line)
        for line in (ctx.evidence.root / "trajectory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    terminal = next(row for row in lines if row["type"] == "terminal")
    assert terminal["usage"]["prompt_tokens"] == 3
    assert terminal["usage"]["completion_tokens"] == 1
    assert terminal["extra"]["foo"] is True
    assert terminal["elapsed_ms"] == 88


def _write_summary_like_run(ctx: AttemptCtx) -> dict[str, Any]:
    """Same omit-when-empty rule as ``application/run.py``."""
    import json

    summary: dict[str, Any] = {"result": {"status": "PASS"}, "facts": ctx.facts_as_list()}
    if ctx.summary_extra:
        summary["extra"] = ctx.summary_extra
    ctx.evidence.write_summary(summary)
    return json.loads((ctx.evidence.root / "summary.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_summary_enrich_lands_on_summary_json(tmp_path: Path) -> None:
    async def enrich(ctx: Any, value: Any, nxt: Any) -> Any:
        del ctx
        bag = dict(await nxt(value) or {})
        bag["probe"] = {"foo": True}
        return bag

    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    graph.chains[SUMMARY_ENRICH] = [
        HandlerRef(plugin_id="probe", handler=enrich, priority=1, source="test")
    ]
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    await record.run(ctx)
    assert ctx.summary_extra == {"probe": {"foo": True}}
    doc = _write_summary_like_run(ctx)
    assert doc["extra"]["probe"]["foo"] is True


@pytest.mark.asyncio
async def test_summary_enrich_omits_empty_bag(tmp_path: Path) -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    await record.run(ctx)
    assert ctx.summary_extra is None
    doc = _write_summary_like_run(ctx)
    assert "extra" not in doc


@pytest.mark.asyncio
async def test_summary_enrich_fail_open_leaves_empty_bag(tmp_path: Path) -> None:
    async def boom(ctx: Any, value: Any, nxt: Any) -> Any:
        del ctx, value, nxt
        raise RuntimeError("summary enrich exploded")

    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    graph.chains[SUMMARY_ENRICH] = [
        HandlerRef(plugin_id="probe", handler=boom, priority=1, source="test")
    ]
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    await record.run(ctx)
    assert ctx.summary_extra is None
    assert any(
        f.name == "slot_failed_open" and f.detail.get("slot") == SUMMARY_ENRICH
        for f in ctx.phase_facts
    )
    doc = _write_summary_like_run(ctx)
    assert "extra" not in doc
