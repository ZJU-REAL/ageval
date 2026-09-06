"""Scoring-box bind at evaluate phase: layers, options, and the chain (#206).

The scoring EnvironmentProvider is constructed after run seals, from the
evaluate-phase profile graphs — not the solver graph, not an empty tuple.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ageval.attempt.ctx import AttemptCtx
from ageval.attempt.phases.evaluate import (
    _ensure_evaluate_host,
    _prepare_evaluate_profiles,
    _scoring_environment_options,
    _scoring_plugin_layers,
    ensure_named_host,
)
from ageval.plugins.defaults import register_defaults
from ageval.plugins.image_layers import ImageLayer
from ageval.plugins.protocol import BindingIntent, ExplicitBinding, HandlerRef
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import AFTER_ENVIRONMENT_READY, ENVIRONMENT, EVALUATION_RUNTIME, EXECUTOR
from ageval.runtime.cancellation import CancellationSignal


class RecordingHost:
    def __init__(self, *, root: Path, kind: str = "docker") -> None:
        self.kind = kind
        self.root = root
        self.started = False
        self.preflighted = False

    async def preflight(self) -> None:
        self.preflighted = True

    async def start(self, *, force_build: bool = False) -> None:
        del force_build
        self.started = True

    async def stop(self, *, delete: bool) -> None:
        del delete


class RawPassRuntime:
    async def evaluate(self, ctx: Any) -> dict[str, Any]:
        del ctx
        return {"status": "PASS", "score": 1}


class StubGraph:
    """The shape binder.graph(pid) really returns: executor + env winners, chains."""

    def __init__(
        self,
        *,
        executor_plugin: str,
        chain_plugin_ids: tuple[str, ...] = (),
    ) -> None:
        self.winners = {
            ENVIRONMENT: SimpleNamespace(plugin_id="fakebox", options=None),
            EXECUTOR: SimpleNamespace(plugin_id=executor_plugin, options=None),
        }
        self.chains: dict[str, list[Any]] = {
            AFTER_ENVIRONMENT_READY: [
                SimpleNamespace(plugin_id=pid, options=None) for pid in chain_plugin_ids
            ]
        }

    def chain(self, slot: str) -> list[Any]:
        return self.chains.get(slot, [])


def _registry(created: list[dict[str, Any]]) -> ExtensionRegistry:
    registry = ExtensionRegistry()
    register_defaults(registry)

    def env_factory(*, spec: Any = None, options: Any = None, plugin_layers: Any = ()) -> Any:
        host = RecordingHost(root=Path(spec.attempt_root))
        created.append(
            {
                "spec": spec,
                "options": dict(options or {}),
                "layers": tuple(tuple(layer) for layer in plugin_layers),
            }
        )
        return host

    registry.exclusive(ENVIRONMENT, "fakebox", env_factory, source="test", is_factory=True)
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
    created: list[dict[str, Any]],
    *,
    lock: Any,
    graphs: dict[str, StubGraph],
    sealed: set[str],
) -> AttemptCtx:
    registry = _registry(created)
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            extensions=[
                ExplicitBinding(slot=ENVIRONMENT, plugin="fakebox"),
                ExplicitBinding(slot=EVALUATION_RUNTIME, plugin="probe"),
            ],
        ),
        registry,
    )
    ctx = AttemptCtx(
        run_id="r",
        trial_id="t",
        attempt_id="a",
        lock=lock,
        profile_id="solver",
        bindings=graph,
        registry=registry,
        services=ServiceTable(),
        host=RecordingHost(root=tmp_path / "agent"),  # type: ignore[arg-type]
        evidence=SimpleNamespace(path=lambda rel: tmp_path / "run" / rel),
        cancellation=CancellationSignal(),
        task_root=tmp_path,
        dataset_root=tmp_path,
    )
    ctx.mark_writers_stopped()
    ctx.phase = "evaluate"
    ctx.agent_service = SimpleNamespace(
        service=SimpleNamespace(
            binder=SimpleNamespace(graph=lambda pid: graphs[pid]),
            _run_profile_ids=sealed,
        )
    )
    return ctx


def _lock(*, overlay: dict[str, Any], refs: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        force_build=False,
        resolved_references=refs,
        job_overlay=overlay,
        agent_profiles=[
            {
                "id": "solver",
                "executor": "acp",
                "model": "entry-default",
                "base_url": "https://solver.example.com/v1",
            },
            {
                "id": "judge",
                "executor": "openai-http",
                "model": "gpt-judge",
                "base_url": "https://api.judge.example.com/v1",
            },
        ],
    )


@pytest.fixture()
def fake_layers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record requested plugin ids; only ``*-plugin`` ones declare image_layers."""
    requested: list[str] = []

    def fake(plugin_ids: frozenset[str]) -> tuple[ImageLayer, ...]:
        requested.extend(sorted(plugin_ids))
        declaring = sorted(pid for pid in plugin_ids if pid.endswith("-plugin"))
        return tuple(
            ImageLayer(plugin_id=pid, dockerfile=Path("D"), package_root=Path("."), body="X")
            for pid in declaring
        )

    monkeypatch.setattr("ageval.plugins.image_layers.layers_for_plugins", fake)
    return requested


@pytest.mark.asyncio
async def test_scoring_host_binds_at_evaluate_with_nested_options_and_layers(
    tmp_path: Path,
    fake_layers: list[str],
) -> None:
    created: list[dict[str, Any]] = []
    lock = _lock(
        overlay={
            "environment": "docker",
            "environment_options": {"egress": "llm", "user": "10001:10001"},
            "evaluate_host": {
                "isolated": True,
                "environment_options": {"egress": "llm", "network": "bridge"},
            },
        },
        refs={"environment_evaluate_dockerfile": "environment/evaluate.Dockerfile"},
    )
    graphs = {
        "solver": StubGraph(executor_plugin="solver-exec", chain_plugin_ids=("solver-plugin",)),
        "judge": StubGraph(executor_plugin="judge-exec", chain_plugin_ids=("judge-plugin",)),
    }
    ctx = _ctx(tmp_path, created, lock=lock, graphs=graphs, sealed={"solver"})

    assert ctx.evaluate_host is None  # composition no longer pre-builds the box
    await _ensure_evaluate_host(ctx)

    assert len(created) == 1
    bind = created[0]
    # Two boxes, two option maps: the nested map wins whole, the agent egress
    # key is not copied over, and the judge allowlist comes from judge hosts.
    assert bind["options"] == {
        "egress": "llm",
        "network": "bridge",
        "egress_allowlist": ["api.judge.example.com"],
    }
    assert "solver-plugin" not in fake_layers
    assert "judge-plugin" in fake_layers
    assert bind["layers"] == (("judge-plugin", "D", ".", "X"),)
    assert ctx.evaluate_host is not None and ctx.evaluate_host.started


@pytest.mark.asyncio
async def test_scoring_options_without_nested_map_inherit_platform_user_python(
    tmp_path: Path,
    fake_layers: list[str],
) -> None:
    created: list[dict[str, Any]] = []
    lock = _lock(
        overlay={
            "environment": "docker",
            "environment_options": {
                "egress": "llm",
                "network": "bridge",
                "platform": "linux/arm64",
                "user": "root",
                "python_version": "3.13",
            },
            "evaluate_host": {"isolated": True},
        },
        refs={
            "environment_evaluate_dockerfile": "environment/evaluate.Dockerfile",
            "evaluation_docker_image": "ageval-eval:grader",
        },
    )
    graphs = {
        "solver": StubGraph(executor_plugin="solver-exec"),
        "judge": StubGraph(executor_plugin="judge-exec"),
    }
    ctx = _ctx(tmp_path, created, lock=lock, graphs=graphs, sealed={"solver"})

    await _ensure_evaluate_host(ctx)

    options = created[0]["options"]
    # Non-inheritance: agent network/egress stay agent-only; platform/user,
    # python_version and the scoring image are the whole story.
    assert options == {
        "platform": "linux/arm64",
        "user": "root",
        "python_version": "3.13",
        "image": "ageval-eval:grader",
    }


def test_scoring_allowlist_unions_nested_extras_not_agent_extras(
    tmp_path: Path, fake_layers: list[str]
) -> None:
    lock = _lock(
        overlay={
            "environment": "docker",
            "environment_options": {
                "egress": "llm",
                "egress_allow": ["registry.npmjs.org"],
            },
            "evaluate_host": {
                "isolated": True,
                "environment_options": {
                    "egress": "llm",
                    "egress_allow": ["extra.judge.example.com"],
                },
            },
        },
        refs={"environment_evaluate_dockerfile": "environment/evaluate.Dockerfile"},
    )
    ctx = _ctx(
        tmp_path,
        [],
        lock=lock,
        graphs={
            "solver": StubGraph(executor_plugin="solver-exec"),
            "judge": StubGraph(executor_plugin="judge-exec"),
        },
        sealed={"solver"},
    )

    options = _scoring_environment_options(ctx)
    assert options["egress_allowlist"] == [
        "api.judge.example.com",
        "extra.judge.example.com",
    ]
    assert "registry.npmjs.org" not in options["egress_allowlist"]
    assert "solver.example.com" not in options["egress_allowlist"]


def test_scoring_layers_follow_seal_set(tmp_path: Path, fake_layers: list[str]) -> None:
    """Sealed solver plugins stay out; unsealed ones (incl. solver) bake in."""
    lock = _lock(overlay={}, refs={})
    graphs = {
        "solver": StubGraph(executor_plugin="solver-exec", chain_plugin_ids=("solver-plugin",)),
        "judge": StubGraph(executor_plugin="judge-exec", chain_plugin_ids=("judge-plugin",)),
    }

    sealed = _ctx(tmp_path, [], lock=lock, graphs=graphs, sealed={"solver"})
    assert _scoring_plugin_layers(sealed) == (("judge-plugin", "D", ".", "X"),)
    assert "solver-plugin" not in fake_layers

    nobody = _ctx(tmp_path, [], lock=lock, graphs=graphs, sealed=set())
    # Run invoked nobody: every declared profile may open at evaluate.
    assert _scoring_plugin_layers(nobody) == (
        ("judge-plugin", "D", ".", "X"),
        ("solver-plugin", "D", ".", "X"),
    )


def test_scoring_options_named_recipe_image_wins(tmp_path: Path, fake_layers: list[str]) -> None:
    lock = _lock(
        overlay={
            "environment": "docker",
            "evaluate_host": {
                "isolated": True,
                "environment_options": {"network": "none"},
            },
        },
        refs={"evaluation_docker_image": "ageval-eval:grader"},
    )
    ctx = _ctx(
        tmp_path,
        [],
        lock=lock,
        graphs={
            "solver": StubGraph(executor_plugin="solver-exec"),
            "judge": StubGraph(executor_plugin="judge-exec"),
        },
        sealed=set(),
    )

    options = _scoring_environment_options(ctx, {"docker_image": "audit:2", "dockerfile": "x"})
    assert options["image"] == "audit:2"
    assert options["network"] == "none"


@pytest.mark.asyncio
async def test_prepare_evaluate_profiles_runs_non_acp_chain(tmp_path: Path) -> None:
    ran: list[str] = []

    async def handler(ctx: Any, value: Any, nxt: Any) -> Any:
        ran.append("judge")
        return await nxt(value)

    lock = _lock(overlay={}, refs={})
    graphs = {
        "solver": StubGraph(executor_plugin="solver-exec"),
        "judge": StubGraph(executor_plugin="judge-exec"),
    }
    graphs["judge"].chains[AFTER_ENVIRONMENT_READY] = [
        HandlerRef(
            plugin_id="judge-hook",
            handler=handler,
            priority=0,
            source="test",
            slot=AFTER_ENVIRONMENT_READY,
        )
    ]
    ctx = _ctx(tmp_path, [], lock=lock, graphs=graphs, sealed={"solver"})

    await _prepare_evaluate_profiles(ctx)

    assert ran == ["judge"]
    facts = [f for f in ctx.phase_facts if f.name == "evaluate_runtime_prepared"]
    assert [f.detail["profile_id"] for f in facts] == ["judge"]


@pytest.mark.asyncio
async def test_named_scoring_host_binds_lazily_with_layers(
    tmp_path: Path, fake_layers: list[str]
) -> None:
    created: list[dict[str, Any]] = []
    lock = _lock(
        overlay={"environment": "docker", "evaluate_host": {"isolated": True}},
        refs={
            "evaluation_environments": {
                "audit": {"dockerfile": "environment/evaluate/audit/Dockerfile"}
            },
        },
    )
    graphs = {
        "solver": StubGraph(executor_plugin="solver-exec", chain_plugin_ids=("solver-plugin",)),
        "judge": StubGraph(executor_plugin="judge-exec", chain_plugin_ids=("judge-plugin",)),
    }
    ctx = _ctx(tmp_path, created, lock=lock, graphs=graphs, sealed={"solver"})

    host = cast(RecordingHost, await ensure_named_host(ctx, "audit"))
    assert host.started
    assert created[0]["layers"] == (("judge-plugin", "D", ".", "X"),)
    assert created[0]["spec"].dockerfile == "environment/evaluate/audit/Dockerfile"
    again = await ensure_named_host(ctx, "audit")
    assert again is host
    assert len(created) == 1


@pytest.mark.asyncio
async def test_scoring_host_without_recipe_stays_none(tmp_path: Path) -> None:
    created: list[dict[str, Any]] = []
    lock = _lock(overlay={"environment": "docker"}, refs={})
    ctx = _ctx(
        tmp_path,
        created,
        lock=lock,
        graphs={
            "solver": StubGraph(executor_plugin="solver-exec"),
            "judge": StubGraph(executor_plugin="judge-exec"),
        },
        sealed={"solver"},
    )

    await _ensure_evaluate_host(ctx)

    assert ctx.evaluate_host is None
    assert created == []
