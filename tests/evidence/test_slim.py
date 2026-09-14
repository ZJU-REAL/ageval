"""Default durable tree drops vendor raw after seal; --keep-vendor-raw keeps it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.attempt.test_eval_seal_phases import _ctx

from ageval.attempt.phases import record
from ageval.evidence.slim import is_vendor_raw_rel, slim_sealed_attempt
from ageval.plugins.defaults import register_defaults
from ageval.plugins.protocol import BindingIntent, HandlerRef
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import TRAJECTORY_COLLECT
from ageval.registry.results_archive import build_attempt_archive


def _seed_invocation(root: Path) -> Path:
    inv = root / "agent" / "invocations" / "001"
    inv.mkdir(parents=True)
    (inv / "metadata.json").write_text(
        '{"seq": 1, "status": "completed", "latency_ms": 10, "profile_id": "solver"}',
        encoding="utf-8",
    )
    (inv / "final-response.json").write_text(
        '{"content": "hi", "usage": {"prompt_tokens": 2, "completion_tokens": 1}}',
        encoding="utf-8",
    )
    (inv / "request.json").write_text(
        '{"messages": [{"content": "go"}]}',
        encoding="utf-8",
    )
    (inv / "events.jsonl").write_text("", encoding="utf-8")
    backend = inv / "backend_raw"
    backend.mkdir()
    (backend / "response.json").write_text('{"id": "x"}\n', encoding="utf-8")
    (root / "agent").mkdir(exist_ok=True)
    (root / "agent" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "evaluation").mkdir(exist_ok=True)
    (root / "evaluation" / "evaluator_raw.json").write_text("{}\n", encoding="utf-8")
    return inv


def test_is_vendor_raw_rel() -> None:
    assert is_vendor_raw_rel("agent/invocations/001/backend_raw/response.json")
    assert is_vendor_raw_rel("agent/invocations/001/request.json")
    assert is_vendor_raw_rel("agent/invocations/001/events.jsonl")
    assert is_vendor_raw_rel("agent/events.jsonl")
    assert is_vendor_raw_rel("evaluation/evaluator_raw.json")
    assert not is_vendor_raw_rel("trajectory.jsonl")
    assert not is_vendor_raw_rel("lock.json")
    assert not is_vendor_raw_rel("result.json")
    assert not is_vendor_raw_rel("summary.json")
    assert not is_vendor_raw_rel("task-artifacts/out.txt")
    assert not is_vendor_raw_rel("evaluation/observation.jsonl")
    assert not is_vendor_raw_rel("evaluation/checks.json")
    assert is_vendor_raw_rel("evaluation/events.jsonl")
    assert is_vendor_raw_rel("evaluation/invocations/001/request.json")
    assert is_vendor_raw_rel("evaluation/invocations/001/backend_raw/raw.json")


def test_slim_deletes_vendor_raw_keeps_jsonl(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    inv = _seed_invocation(root)
    (root / "trajectory.jsonl").write_text('{"type":"terminal"}\n', encoding="utf-8")
    (root / "lock.json").write_text("{}\n", encoding="utf-8")
    slim_sealed_attempt(root)
    assert (root / "trajectory.jsonl").is_file()
    assert (root / "lock.json").is_file()
    assert inv.is_dir()
    assert not (inv / "backend_raw").exists()
    assert not (inv / "request.json").exists()
    assert not (inv / "events.jsonl").exists()
    assert not (inv / "final-response.json").exists()
    assert not (inv / "metadata.json").exists()
    assert not (root / "agent" / "events.jsonl").exists()
    assert not (root / "evaluation" / "evaluator_raw.json").exists()


def test_slim_keeps_observation_jsonl_drops_eval_vendor_raw(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    eval_inv = root / "evaluation" / "invocations" / "0001-judge"
    eval_inv.mkdir(parents=True)
    (eval_inv / "request.json").write_text('{"messages":[{"content":"gold"}]}\n', encoding="utf-8")
    (eval_inv / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (eval_inv / "backend_raw").mkdir()
    (eval_inv / "backend_raw" / "raw.json").write_text("{}\n", encoding="utf-8")
    (root / "evaluation" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "evaluation" / "evaluator_raw.json").write_text("{}\n", encoding="utf-8")
    (root / "evaluation" / "observation.jsonl").write_text(
        '{"type":"terminal","profile_id":"judge"}\n', encoding="utf-8"
    )
    (root / "evaluation" / "checks.json").write_text(
        '{"schema":"ageval.evaluation.checks/1","checks":[{"id":"audit"}]}\n',
        encoding="utf-8",
    )
    slim_sealed_attempt(root)
    assert (root / "evaluation" / "observation.jsonl").is_file()
    assert (root / "evaluation" / "checks.json").is_file()
    assert not (root / "evaluation" / "evaluator_raw.json").exists()
    assert not (root / "evaluation" / "events.jsonl").exists()
    assert eval_inv.is_dir()
    assert not (eval_inv / "request.json").exists()
    assert not (eval_inv / "backend_raw").exists()


@pytest.mark.asyncio
async def test_record_drops_vendor_raw_after_seal(tmp_path: Path) -> None:
    async def collect(ctx: Any, value: Any, nxt: Any) -> Any:
        del ctx
        assert (tmp_path / "run" / "agent" / "invocations" / "001" / "events.jsonl").is_file()
        return await nxt(value)

    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    graph.chains[TRAJECTORY_COLLECT] = [
        HandlerRef(plugin_id="probe", handler=collect, priority=1, source="test")
    ]
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    _seed_invocation(ctx.evidence.root)
    await record.run(ctx)
    assert (ctx.evidence.root / "trajectory.jsonl").is_file()
    inv = ctx.evidence.root / "agent" / "invocations" / "001"
    assert inv.is_dir()
    assert not (inv / "backend_raw").exists()
    assert not (inv / "request.json").exists()
    last = json.loads((ctx.evidence.root / "trajectory.jsonl").read_text().splitlines()[-1])
    assert last["type"] == "terminal"


@pytest.mark.asyncio
async def test_record_keep_vendor_raw_retains_layer_b(tmp_path: Path) -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    graph = resolve(BindingIntent(profile_id="solver"), registry)
    ctx = _ctx(tmp_path, registry=registry, graph=graph)
    ctx.keep_vendor_raw = True
    _seed_invocation(ctx.evidence.root)
    await record.run(ctx)
    inv = ctx.evidence.root / "agent" / "invocations" / "001"
    assert (inv / "backend_raw" / "response.json").is_file()
    assert (inv / "request.json").is_file()
    assert (inv / "events.jsonl").is_file()
    assert (ctx.evidence.root / "trajectory.jsonl").is_file()


def test_archive_skips_vendor_raw_unless_flag(tmp_path: Path) -> None:
    run_id = "run_slim"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "lock.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "result.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "trajectory.jsonl").write_text("{}\n", encoding="utf-8")
    (run_dir / "evaluation").mkdir()
    (run_dir / "evaluation" / "observation.jsonl").write_text("{}\n", encoding="utf-8")
    (run_dir / "evaluation" / "checks.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "evaluation" / "evaluator_raw.json").write_text("{}\n", encoding="utf-8")
    eval_inv = run_dir / "evaluation" / "invocations" / "001"
    eval_inv.mkdir(parents=True)
    (eval_inv / "request.json").write_text("{}\n", encoding="utf-8")
    inv = run_dir / "agent" / "invocations" / "001"
    inv.mkdir(parents=True)
    (inv / "request.json").write_text("{}\n", encoding="utf-8")
    (inv / "backend_raw").mkdir()
    (inv / "backend_raw" / "raw.json").write_text("{}\n", encoding="utf-8")

    slim, _, _ = build_attempt_archive(run_dir, run_id=run_id)
    fat, _, _ = build_attempt_archive(run_dir, run_id=run_id, keep_vendor_raw=True)

    import gzip
    import io
    import tarfile

    def names(archive: bytes) -> set[str]:
        with (
            gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz,
            tarfile.open(fileobj=gz, mode="r:") as tar,
        ):
            return {m.name for m in tar.getmembers() if m.isfile()}

    prefix = f".ageval/runs/{run_id}"
    slim_names = names(slim)
    fat_names = names(fat)
    assert f"{prefix}/trajectory.jsonl" in slim_names
    assert f"{prefix}/lock.json" in slim_names
    assert f"{prefix}/evaluation/observation.jsonl" in slim_names
    assert f"{prefix}/evaluation/checks.json" in slim_names
    assert f"{prefix}/evaluation/evaluator_raw.json" not in slim_names
    assert f"{prefix}/evaluation/invocations/001/request.json" not in slim_names
    assert f"{prefix}/evaluation/evaluator_raw.json" in fat_names
    assert f"{prefix}/evaluation/invocations/001/request.json" in fat_names
    assert not any("backend_raw" in n for n in slim_names)
    assert not any(n.endswith("/request.json") for n in slim_names)
    assert f"{prefix}/agent/invocations/001/request.json" in fat_names
    assert f"{prefix}/agent/invocations/001/backend_raw/raw.json" in fat_names
