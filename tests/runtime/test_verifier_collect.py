"""evaluation.collect runs before the evaluator and fails closed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases import evaluate
from ageval.attempt.verifier_collect import collect_declared_artifacts, place_collected_artifacts
from ageval.environments.protocol import EnvironmentFailure, ExecResult
from ageval.evidence.store import VERIFIER_COLLECT_REL, AttemptEvidenceStore
from ageval.plugins.defaults import register_defaults
from ageval.plugins.protocol import BindingIntent, ExplicitBinding
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import EVALUATION_RUNTIME
from ageval.runtime.cancellation import CancellationSignal

FINALIZE = "curl -H 'Authorization: Bearer s3cr3t-token' http://localhost/finalize"
_LIVE_DATABASE = [
    {"path": "/tmp/results.json", "service": "customer", "command": "snapshot-customer"},
    {"path": "/tmp/pg.dump", "service": "postgres-db", "command": "pg_dump"},
    {"path": "/tmp/redis.rdb", "service": "redis", "command": "redis-cli"},
    {"command": FINALIZE},
    {"path": "/tmp/agent.patch", "service": "main", "command": "git diff"},
]


class _Evidence:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / name


class _Box:
    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        trees: dict[str, dict[str, bytes]] | None = None,
        fail_script: str | None = None,
        stderr: str = "",
    ) -> None:
        self.files = files or {}
        self.trees = trees or {}
        self.fail_script = fail_script
        self.stderr = stderr
        self.calls: list[tuple[Any, ...]] = []

    async def exec(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float | None = None,
        user: str | None = None,
        service: str | None = None,
    ) -> ExecResult:
        del cwd, env, user
        script = command[-1] if command else ""
        self.calls.append(("exec", service, timeout_sec, script))
        if self.fail_script is not None and script == self.fail_script:
            return ExecResult(exit_code=1, stderr=self.stderr)
        return ExecResult(0)

    async def download(self, source: str, dest: Path, service: str | None = None) -> None:
        self.calls.append(("download", source, service))
        if source in self.trees:
            dest.mkdir(parents=True, exist_ok=True)
            for name, body in self.trees[source].items():
                target = dest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            return
        if source not in self.files:
            raise EnvironmentFailure("environment_download_missing", source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[source])

    async def upload(self, source: Path, dest: str) -> None:
        self.calls.append(("upload", dest, source.read_bytes() if source.is_file() else b""))


def _ctx(
    tmp_path: Path,
    host: _Box,
    rows: list[dict[str, Any]] | None,
    *,
    regrade: bool = False,
    stopped: bool = True,
) -> SimpleNamespace:
    facts: list[dict[str, Any]] = []

    def record_fact(name: str, detail: dict[str, Any] | None = None) -> None:
        facts.append({"name": name, "detail": dict(detail or {})})

    def assert_writers_stopped() -> None:
        if not stopped:
            raise RuntimeError("writers")

    refs: dict[str, Any] = {}
    if rows is not None:
        refs["evaluation_collect"] = rows
    return SimpleNamespace(
        host=host,
        lock=SimpleNamespace(resolved_references=refs),
        evidence=_Evidence(tmp_path),
        record_fact=record_fact,
        assert_writers_stopped=assert_writers_stopped,
        regrade=regrade,
        facts=facts,
    )


def _files() -> dict[str, bytes]:
    return {
        "/tmp/results.json": b'{"n":1}',
        "/tmp/pg.dump": b"PGDMP",
        "/tmp/redis.rdb": b"REDIS",
        "/tmp/agent.patch": b"diff",
        "/shared/verify_snapshot.json": b"{}",
        "/tmp/kafka-snapshot.tgz": b"tgz",
    }


@pytest.mark.asyncio
async def test_live_database_shape_runs_main_before_sidecars(tmp_path: Path) -> None:
    host = _Box(_files())
    ctx = _ctx(tmp_path, host, _LIVE_DATABASE)
    await collect_declared_artifacts(ctx)
    await place_collected_artifacts(ctx, host)

    assert host.calls == [
        ("exec", None, 60.0, FINALIZE),
        ("exec", None, 60.0, "git diff"),
        ("download", "/tmp/agent.patch", None),
        ("exec", "customer", 60.0, "snapshot-customer"),
        ("exec", "postgres-db", 60.0, "pg_dump"),
        ("exec", "redis", 60.0, "redis-cli"),
        ("download", "/tmp/results.json", "customer"),
        ("download", "/tmp/pg.dump", "postgres-db"),
        ("download", "/tmp/redis.rdb", "redis"),
        ("upload", "/tmp/results.json", b'{"n":1}'),
        ("upload", "/tmp/pg.dump", b"PGDMP"),
        ("upload", "/tmp/redis.rdb", b"REDIS"),
        ("upload", "/tmp/agent.patch", b"diff"),
    ]
    manifest = json.loads(
        (tmp_path / VERIFIER_COLLECT_REL / "manifest.json").read_text(encoding="utf-8")
    )
    assert [row["index"] for row in manifest["entries"]] == [0, 1, 2, 4]
    blob = json.dumps({"facts": ctx.facts, "manifest": manifest})
    assert "s3cr3t-token" not in blob
    assert FINALIZE not in blob
    assert "command" not in blob
    collected = next(fact for fact in ctx.facts if fact["name"] == "verifier_collected")
    assert collected["detail"]["entries"][3] == {"service": "main", "status": "ran"}
    placed = next(fact for fact in ctx.facts if fact["name"] == "verifier_collect_placed")
    assert placed["detail"] == {"count": 4}


@pytest.mark.asyncio
async def test_ctr_and_payments_shapes_use_the_sidecar(tmp_path: Path) -> None:
    ctr = _Box(_files())
    await collect_declared_artifacts(
        _ctx(
            tmp_path / "ctr",
            ctr,
            [
                {
                    "path": "/shared/verify_snapshot.json",
                    "service": "api",
                    "command": "curl -sf http://localhost:5000/healthz",
                    "timeout_sec": 10,
                }
            ],
        )
    )
    assert ctr.calls == [
        ("exec", "api", 10.0, "curl -sf http://localhost:5000/healthz"),
        ("download", "/shared/verify_snapshot.json", "api"),
    ]

    payments = _Box(_files())
    await collect_declared_artifacts(
        _ctx(
            tmp_path / "pay",
            payments,
            [
                {
                    "path": "/tmp/kafka-snapshot.tgz",
                    "service": "kafka",
                    "command": "tar czf /tmp/kafka-snapshot.tgz /var/lib/kafka",
                    "timeout_sec": 120,
                }
            ],
        )
    )
    assert payments.calls == [
        ("exec", "kafka", 120.0, "tar czf /tmp/kafka-snapshot.tgz /var/lib/kafka"),
        ("download", "/tmp/kafka-snapshot.tgz", "kafka"),
    ]


@pytest.mark.asyncio
async def test_empty_collect_does_not_touch_the_box(tmp_path: Path) -> None:
    host = _Box()
    await collect_declared_artifacts(_ctx(tmp_path, host, None))
    await collect_declared_artifacts(_ctx(tmp_path / "empty", host, []))
    await place_collected_artifacts(_ctx(tmp_path, host, None), host)
    assert host.calls == []


@pytest.mark.asyncio
async def test_command_failure_stops_before_later_copies(tmp_path: Path) -> None:
    host = _Box(
        _files(),
        fail_script="finalize-broken",
        stderr="Authorization: Bearer leaked-token",
    )
    ctx = _ctx(
        tmp_path,
        host,
        [
            {"command": "finalize-broken"},
            {"path": "/tmp/agent.patch", "command": "git diff"},
        ],
    )
    with pytest.raises(EnvironmentFailure, match="exit 1") as caught:
        await collect_declared_artifacts(ctx)
    assert caught.value.kind == "environment_collect_failed"
    assert "finalize-broken" not in caught.value.message
    assert "leaked-token" not in caught.value.message
    assert "git diff" not in caught.value.message
    assert [call[0] for call in host.calls] == ["exec"]
    assert not (tmp_path / VERIFIER_COLLECT_REL / "manifest.json").exists()


@pytest.mark.asyncio
async def test_missing_sidecar_path_is_typed(tmp_path: Path) -> None:
    host = _Box()
    ctx = _ctx(
        tmp_path,
        host,
        [
            {"path": "/tmp/missing.json", "service": "api", "command": "snapshot"},
            {"path": "/tmp/later.json", "service": "api"},
        ],
    )
    with pytest.raises(EnvironmentFailure, match="missing") as caught:
        await collect_declared_artifacts(ctx)
    assert caught.value.kind == "environment_collect_missing"
    assert host.calls[-1][1] == "/tmp/missing.json"
    assert "/tmp/later.json" not in [call[1] for call in host.calls if call[0] == "download"]


@pytest.mark.asyncio
async def test_regrade_replays_the_snapshot_without_commands(tmp_path: Path) -> None:
    host = _Box(_files())
    ctx = _ctx(tmp_path, host, [{"path": "/tmp/agent.patch", "command": "git diff"}])
    await collect_declared_artifacts(ctx)
    host.calls.clear()
    ctx.regrade = True
    ctx.facts.clear()
    await collect_declared_artifacts(ctx)
    await place_collected_artifacts(ctx, host)
    assert [call[0] for call in host.calls] == ["upload"]
    assert host.calls[0][1] == "/tmp/agent.patch"


@pytest.mark.asyncio
async def test_regrade_without_a_snapshot_fails_closed(tmp_path: Path) -> None:
    host = _Box()
    ctx = _ctx(tmp_path, host, [{"path": "/tmp/agent.patch"}], regrade=True)
    with pytest.raises(EnvironmentFailure, match="agent.patch") as caught:
        await collect_declared_artifacts(ctx)
    assert caught.value.kind == "environment_collect_missing"
    assert host.calls == []


@pytest.mark.asyncio
async def test_regrade_command_only_does_not_exec(tmp_path: Path) -> None:
    host = _Box()
    ctx = _ctx(tmp_path, host, [{"command": FINALIZE}], regrade=True)
    await collect_declared_artifacts(ctx)
    assert host.calls == []


@pytest.mark.asyncio
async def test_writers_must_be_stopped(tmp_path: Path) -> None:
    host = _Box(_files())
    ctx = _ctx(tmp_path, host, [{"path": "/tmp/agent.patch"}], stopped=False)
    with pytest.raises(RuntimeError, match="writers"):
        await collect_declared_artifacts(ctx)
    assert host.calls == []


@pytest.mark.asyncio
async def test_directory_exclude_is_pruned_after_copy(tmp_path: Path) -> None:
    host = _Box(trees={"/app/src": {"keep.txt": b"keep", "skip.log": b"no"}})
    ctx = _ctx(
        tmp_path,
        host,
        [{"path": "/app/src", "service": "api", "exclude": ["*.log"]}],
    )
    await collect_declared_artifacts(ctx)
    staged = tmp_path / VERIFIER_COLLECT_REL / "entries" / "0" / "src"
    assert (staged / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (staged / "skip.log").exists()


def _scoring_ctx(tmp_path: Path, host: _Box, rows: list[dict[str, Any]]) -> AttemptCtx:
    registry = ExtensionRegistry()
    register_defaults(registry)

    class _Runtime:
        async def evaluate(self, ctx: Any) -> dict[str, Any]:
            host.calls.append(("evaluate",))
            del ctx
            return {"status": "PASS", "score": 1}

    registry.exclusive(
        EVALUATION_RUNTIME,
        "probe",
        lambda **_kwargs: _Runtime(),
        source="test",
        is_factory=True,
    )
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="probe")],
        ),
        registry,
    )
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=SimpleNamespace(  # type: ignore[arg-type]
            resolved_references={"evaluation_collect": rows},
            limits=None,
            agent_profiles=(),
            force_build=False,
        ),
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=host,  # type: ignore[arg-type]
        evidence=AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r"),
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
    )
    ctx.mark_writers_stopped()
    return ctx


@pytest.mark.asyncio
async def test_evaluate_places_the_patch_before_the_evaluator(tmp_path: Path) -> None:
    host = _Box(_files())
    ctx = _scoring_ctx(
        tmp_path,
        host,
        [{"path": "/tmp/agent.patch", "command": "git diff"}],
    )
    await evaluate.run(ctx)
    assert [call[0] for call in host.calls] == ["exec", "download", "upload", "evaluate"]
    assert host.calls[2][1] == "/tmp/agent.patch"
    assert ctx.evaluation_result == {"status": "PASS", "score": 1}


@pytest.mark.asyncio
async def test_evaluate_stops_when_the_collect_command_fails(tmp_path: Path) -> None:
    host = _Box(fail_script="git diff", stderr="no")
    ctx = _scoring_ctx(tmp_path, host, [{"path": "/tmp/agent.patch", "command": "git diff"}])
    with pytest.raises(EnvironmentFailure) as caught:
        await evaluate.run(ctx)
    assert caught.value.kind == "environment_collect_failed"
    assert [call[0] for call in host.calls] == ["exec"]
    assert ctx.evaluation_result is None
