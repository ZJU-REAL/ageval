"""Lock rejects a model the executor cannot send, before the lock is written."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.helpers.lock import lock_with_profiles

from ageval.config.errors import ConfigError
from ageval.config.profiles import parse_job_mapping
from ageval.environments.protocol import EnvironmentCapabilities
from ageval.model.errors import ModelConfigError
from ageval.model.spec import ModelSpec, require_model_support
from ageval.plugins.base import BaseExecutor
from ageval.plugins.defaults import register_defaults
from ageval.plugins.errors import (
    ExtensionRegistryError,
    InjectUnsatisfiedError,
    PluginContractError,
)
from ageval.plugins.lock_bind import extension_graph_to_lock
from ageval.plugins.model_contract import YamlOnlyExecutorWarning
from ageval.plugins.protocol import BindingIntent, InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

_TASK = "format: ageval.task/1\ntask_id: t\nagent_profiles:\n  - id: solver\n"


def _task(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.yaml").write_text(_TASK, encoding="utf-8")
    (root / "run.py").write_text("async def run(ctx): pass\n", encoding="utf-8")
    (root / "evaluator.py").write_text("def evaluate(i): return {}\n", encoding="utf-8")
    return root


def _lock(tmp_path: Path, profile: dict[str, Any], *, environment: str = "local") -> Any:
    return lock_with_profiles(
        _task(tmp_path / "t"),
        "t",
        {"solver": profile},
        environment=environment,
    )


@pytest.fixture
def registry() -> Iterator[ExtensionRegistry]:
    """Bootstrap, then put exclusive rows and injects back after the test."""
    from ageval.plugins.bootstrap import ensure_bootstrapped

    reg = ensure_bootstrapped()
    rows = {slot: dict(items) for slot, items in reg._rows.items()}
    injects = dict(reg._injects)
    services = dict(reg._services)
    try:
        yield reg
    finally:
        reg._rows.clear()
        reg._rows.update({slot: dict(items) for slot, items in rows.items()})
        reg._injects.clear()
        reg._injects.update(injects)
        reg._services.clear()
        reg._services.update(services)


class NeedsBox(BaseExecutor):
    """Class winner used only by these tests. Empty allowlist rejects every extra."""

    kind = "needs-box"
    requires_environment = True
    supported_apis = frozenset({"chat"})
    supported_model_fields = frozenset({"id", "api", "extra"})
    extra_allowlist = frozenset()

    @classmethod
    def supports_model(cls, spec: ModelSpec) -> None:
        require_model_support(
            spec,
            supported_apis=cls.supported_apis,
            supported_model_fields=cls.supported_model_fields,
            extra_allowlist=cls.extra_allowlist,
        )

    def bind_model(self, spec: ModelSpec) -> None:
        self.spec = spec

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        del prompt, timeout, collect_dir, redaction_sentinels, tools, messages

    def close(self) -> None:
        return None


def _register_needs_box(
    reg: ExtensionRegistry,
    *,
    environment: type[Any] | None,
    capabilities: tuple[str, ...] | None,
) -> None:
    reg.exclusive(EXECUTOR, NeedsBox.kind, NeedsBox, source="test", is_factory=True)
    if environment is not None:
        reg.exclusive(ENVIRONMENT, "box", environment, source="test", is_factory=True)
    if capabilities is not None:
        reg.declare_inject(
            NeedsBox.kind,
            (InjectRequirement(service=ENVIRONMENT, capabilities=capabilities),),
        )


class _ExecHost:
    capabilities = EnvironmentCapabilities(exec=True)


class _MuteHost:
    capabilities = EnvironmentCapabilities(attach_stdio=True)


def test_valid_nested_profile_locks_after_supports_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ageval.plugins.contrib.openai_http.executor import OpenAIHTTPExecutor

    order: list[str] = []
    real_supports = OpenAIHTTPExecutor.supports_model

    def spy_supports(spec: ModelSpec) -> None:
        order.append("supports_model")
        real_supports(spec)

    def spy_lock(graph: Any) -> dict[str, Any]:
        order.append("write_lock")
        return extension_graph_to_lock(graph)

    monkeypatch.setattr(OpenAIHTTPExecutor, "supports_model", staticmethod(spy_supports))
    monkeypatch.setattr("ageval.plugins.lock_bind.extension_graph_to_lock", spy_lock)
    locked = _lock(
        tmp_path,
        {
            "executor": "openai-http",
            "model": {
                "id": "gpt-4.1-mini",
                "api": "chat",
                "reasoning": {"effort": "xhigh"},
                "extra": {"provider": {"order": ["a"]}},
            },
        },
    )
    assert order == ["supports_model", "write_lock"]
    bindings = locked.extension_bindings["solver"]["slots"]["executor"]
    assert bindings["plugin"] == "openai-http"
    assert locked.digest


def test_acp_nested_profile_still_locks(tmp_path: Path) -> None:
    locked = _lock(
        tmp_path,
        {
            "executor": "acp",
            "model": {"id": "zai-coding-cn/glm-5.3", "reasoning": {"effort": "xhigh"}},
            "options": {"entry": "pi"},
        },
    )
    assert locked.extension_bindings["solver"]["slots"]["executor"]["plugin"] == "acp"


def test_unsupported_api_is_model_config_error(tmp_path: Path) -> None:
    with pytest.raises(ModelConfigError, match="model_api_unsupported:responses") as caught:
        _lock(
            tmp_path,
            {
                "executor": "anthropic-http",
                "model": {"id": "claude-sonnet-4-6", "api": "responses"},
            },
        )
    assert caught.value.kind == "model_config"
    assert not isinstance(caught.value, ExtensionRegistryError)


def test_unsupported_field_is_model_config_error(tmp_path: Path) -> None:
    with pytest.raises(ModelConfigError, match="model_field_unsupported:timeout"):
        _lock(
            tmp_path,
            {"executor": "acp", "model": {"id": "m", "timeout": 30}, "options": {"entry": "pi"}},
        )


def test_extra_outside_allowlist_is_model_config_error(tmp_path: Path) -> None:
    with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
        _lock(
            tmp_path,
            {
                "executor": "openai-http",
                "model": {"id": "gpt-4.1-mini", "extra": {"temperature": 0}},
            },
        )


def test_empty_allowlist_rejects_any_extra(tmp_path: Path, registry: ExtensionRegistry) -> None:
    _register_needs_box(registry, environment=None, capabilities=("exec",))
    with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
        _lock(
            tmp_path,
            {"executor": NeedsBox.kind, "model": {"id": "m", "extra": {"temperature": 1}}},
        )


def test_rejected_extra_does_not_write_the_lock(
    tmp_path: Path, registry: ExtensionRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register_needs_box(registry, environment=None, capabilities=("exec",))
    calls = {"n": 0}

    def spy(graph: Any) -> dict[str, Any]:
        calls["n"] += 1
        return extension_graph_to_lock(graph)

    monkeypatch.setattr("ageval.plugins.lock_bind.extension_graph_to_lock", spy)
    with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
        _lock(
            tmp_path,
            {"executor": NeedsBox.kind, "model": {"id": "m", "extra": {"temperature": 1}}},
        )
    assert calls["n"] == 0


def test_flat_extra_body_stays_a_model_config_error() -> None:
    with pytest.raises(ConfigError, match="model_flat_rejected:extra_body") as caught:
        parse_job_mapping(
            {
                "format": "ageval.profiles/1",
                "environment": "local",
                "agent_profiles": {
                    "solver": {
                        "executor": "openai-http",
                        "model": {"id": "m"},
                        "options": {"extra_body": {"temperature": 0}},
                    }
                },
            }
        )
    assert caught.value.error_code == "model_config"
    assert isinstance(caught.value.__cause__, ModelConfigError)


def test_requires_environment_without_a_winner_is_plugin_contract() -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    _register_needs_box(registry, environment=None, capabilities=("exec",))
    with pytest.raises(PluginContractError, match="no environment winner") as caught:
        resolve(BindingIntent(profile_id="solver", executor=NeedsBox.kind), registry)
    assert caught.value.kind == "plugin_contract"


def test_requires_environment_without_inject_is_plugin_contract() -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    _register_needs_box(registry, environment=_ExecHost, capabilities=None)
    with pytest.raises(PluginContractError, match="does not inject"):
        resolve(
            BindingIntent(profile_id="solver", environment="box", executor=NeedsBox.kind),
            registry,
        )


def test_requires_environment_missing_caps_is_plugin_contract() -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    _register_needs_box(registry, environment=_MuteHost, capabilities=("exec",))
    with pytest.raises(PluginContractError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="box", executor=NeedsBox.kind),
            registry,
        )


def test_requires_environment_with_caps_resolves() -> None:
    registry = ExtensionRegistry()
    register_defaults(registry)
    _register_needs_box(registry, environment=_ExecHost, capabilities=("exec",))
    graph = resolve(
        BindingIntent(
            profile_id="solver",
            environment="box",
            executor=NeedsBox.kind,
            model={"id": "m"},
        ),
        registry,
    )
    assert graph.winners[EXECUTOR].plugin_id == NeedsBox.kind
    assert graph.winners[ENVIRONMENT].plugin_id == "box"


def test_lock_requires_environment_unmet(tmp_path: Path, registry: ExtensionRegistry) -> None:
    _register_needs_box(registry, environment=None, capabilities=None)
    with pytest.raises(PluginContractError, match="does not inject"):
        _lock(tmp_path, {"executor": NeedsBox.kind, "model": {"id": "m"}})


def test_yaml_only_executor_warns_and_locks(tmp_path: Path, registry: ExtensionRegistry) -> None:
    def build_yaml(**_kwargs: Any) -> object:
        return object()

    registry.exclusive(EXECUTOR, "yaml-exec", build_yaml, source="test", is_factory=True)
    with pytest.warns(YamlOnlyExecutorWarning, match="yaml-exec"):
        locked = _lock(
            tmp_path,
            {"executor": "yaml-exec", "model": {"id": "m", "extra": {"temperature": 1}}},
        )
    assert locked.extension_bindings["solver"]["slots"]["executor"]["plugin"] == "yaml-exec"


def test_yaml_only_executor_strict_mode_is_plugin_contract(
    tmp_path: Path, registry: ExtensionRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build_yaml(**_kwargs: Any) -> object:
        return object()

    registry.exclusive(EXECUTOR, "yaml-exec", build_yaml, source="test", is_factory=True)
    monkeypatch.setenv("AGEVAL_STRICT_MODEL_CONTRACT", "1")
    with pytest.raises(PluginContractError, match="no decorated model contract"):
        _lock(tmp_path, {"executor": "yaml-exec", "model": {"id": "m"}})


def test_first_party_yaml_only_fails_when_env_unset(
    tmp_path: Path, registry: ExtensionRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build_yaml(**_kwargs: Any) -> object:
        return object()

    monkeypatch.delenv("AGEVAL_STRICT_MODEL_CONTRACT", raising=False)
    registry.exclusive(EXECUTOR, "yaml-exec", build_yaml, source="first-party", is_factory=True)
    with pytest.raises(PluginContractError, match="no decorated model contract"):
        _lock(tmp_path, {"executor": "yaml-exec", "model": {"id": "m"}})


def test_installed_yaml_only_warns_that_cutoff_is_unpublished(
    tmp_path: Path, registry: ExtensionRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build_yaml(**_kwargs: Any) -> object:
        return object()

    monkeypatch.delenv("AGEVAL_STRICT_MODEL_CONTRACT", raising=False)
    registry.exclusive(EXECUTOR, "yaml-exec", build_yaml, source="installed", is_factory=True)
    with pytest.warns(
        YamlOnlyExecutorWarning, match="cutoff for third-party factories is not published"
    ):
        locked = _lock(tmp_path, {"executor": "yaml-exec", "model": {"id": "m"}})
    assert locked.extension_bindings["solver"]["slots"]["executor"]["plugin"] == "yaml-exec"


def test_yaml_only_strict_off_still_warns(
    tmp_path: Path, registry: ExtensionRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build_yaml(**_kwargs: Any) -> object:
        return object()

    registry.exclusive(EXECUTOR, "yaml-exec", build_yaml, source="test", is_factory=True)
    monkeypatch.setenv("AGEVAL_STRICT_MODEL_CONTRACT", "0")
    with pytest.warns(YamlOnlyExecutorWarning, match="yaml-exec"):
        _lock(tmp_path, {"executor": "yaml-exec", "model": {"id": "m"}})


def test_function_factory_missing_caps_stay_inject_unsatisfied() -> None:
    """A yaml factory is not a class contract. Missing caps stay InjectUnsatisfiedError."""

    def build_yaml(**_kwargs: Any) -> object:
        return object()

    registry = ExtensionRegistry()
    register_defaults(registry)
    registry.exclusive(ENVIRONMENT, "mute", _MuteHost, source="test", is_factory=True)
    registry.exclusive(EXECUTOR, "yaml-exec", build_yaml, source="test", is_factory=True)
    registry.declare_inject(
        "yaml-exec",
        (InjectRequirement(service=ENVIRONMENT, capabilities=("exec",)),),
    )
    with pytest.raises(InjectUnsatisfiedError, match="exec"):
        resolve(
            BindingIntent(profile_id="solver", environment="mute", executor="yaml-exec"),
            registry,
        )
