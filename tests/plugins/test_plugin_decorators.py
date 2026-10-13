"""@environment_plugin / @executor_plugin write the process ExtensionRegistry."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, cast

import pytest

from ageval.environments.protocol import EnvironmentCapabilities, ExecResult, Placement
from ageval.plugins.base import BaseEnvironment, BaseExecutor
from ageval.plugins.decorators import environment_plugin, executor_plugin
from ageval.plugins.errors import ExtensionRegistryError, PluginContractError
from ageval.plugins.registry import ExtensionRegistry, get_global_registry
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

_ENV_KIND = "decorator-env"
_EXEC_KIND = "decorator-exec"


@pytest.fixture
def process_registry() -> Iterator[ExtensionRegistry]:
    """Decorators write the process registry. Put its rows back after the test."""
    registry = get_global_registry()
    saved = {slot: dict(rows) for slot, rows in registry._rows.items()}
    try:
        yield registry
    finally:
        registry._rows.clear()
        registry._rows.update({slot: dict(rows) for slot, rows in saved.items()})


async def _preflight(_self: Any) -> None:
    return None


async def _start(_self: Any, *, force_build: bool = False) -> None:
    del force_build


async def _stop(_self: Any, *, delete: bool) -> None:
    del delete


def _placement(_self: Any) -> Placement:
    return Placement(target_id="decorator")


def _visible_path(_self: Any, box_path: str) -> str:
    return box_path


async def _exec(_self: Any, command: Sequence[str], **_kwargs: Any) -> ExecResult:
    del command
    return ExecResult(0)


async def _upload(_self: Any, source: object, dest: str) -> None:
    del source, dest


async def _download(_self: Any, source: str, dest: object) -> None:
    del source, dest


async def _attach(_self: Any, argv: Sequence[str], **_kwargs: Any) -> Any:
    del argv
    raise AssertionError("not used")


_ENV_METHODS: dict[str, Any] = {
    "preflight": _preflight,
    "start": _start,
    "stop": _stop,
    "placement": _placement,
    "visible_path": _visible_path,
    "exec": _exec,
    "upload": _upload,
    "download": _download,
    "attach_stdio": _attach,
}


def _environment_type(
    kind: str = _ENV_KIND,
    *,
    capabilities: EnvironmentCapabilities | None = None,
    omit: set[str] | None = None,
    **extra: Any,
) -> type[BaseEnvironment]:
    body: dict[str, Any] = {
        "kind": kind,
        "capabilities": capabilities
        if capabilities is not None
        else EnvironmentCapabilities(
            exec=True,
            upload=True,
            download=True,
            attach_stdio=True,
            uid_gid=True,
            path_views=True,
            compose=True,
        ),
        "python_command": ("python3",),
    }
    body.update(_ENV_METHODS)
    for name in omit or ():
        body.pop(name, None)
    body.update(extra)
    return cast(type[BaseEnvironment], type("StubEnvironment", (BaseEnvironment,), body))


def _supports_model(_self: Any, spec: Any) -> None:
    del spec


def _bind_model(_self: Any, spec: Any) -> None:
    del spec


def _invoke(_self: Any, prompt: str, **_kwargs: Any) -> str:
    return prompt


def _close(_self: Any) -> None:
    return None


_EXEC_METHODS: dict[str, Any] = {
    "supports_model": _supports_model,
    "bind_model": _bind_model,
    "invoke": _invoke,
    "close": _close,
}


def _executor_type(
    kind: str = _EXEC_KIND,
    *,
    omit: set[str] | None = None,
    **extra: Any,
) -> type[BaseExecutor]:
    body: dict[str, Any] = {
        "kind": kind,
        "requires_environment": False,
        "supported_apis": frozenset({"chat", "responses"}),
        "supported_model_fields": frozenset(
            {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
        ),
        "extra_allowlist": frozenset({"provider"}),
    }
    body.update(_EXEC_METHODS)
    for name in omit or ():
        body.pop(name, None)
    body.update(extra)
    return cast(type[BaseExecutor], type("StubExecutor", (BaseExecutor,), body))


def _row(registry: ExtensionRegistry, slot: str, plugin_id: str) -> Any:
    return registry.get_registration(slot, plugin_id)


def test_environment_class_is_an_exclusive_candidate(process_registry: ExtensionRegistry) -> None:
    cls = environment_plugin(priority=100, source="first-party")(_environment_type())
    assert process_registry is get_global_registry()
    row = _row(process_registry, ENVIRONMENT, _ENV_KIND)
    assert row is not None
    assert row.impl is cls
    assert row.priority == 100
    assert row.source == "first-party"
    assert row.is_factory is True
    assert row.impl.capabilities.exec is True
    found = [
        item for item in process_registry.candidates(ENVIRONMENT) if item.plugin_id == _ENV_KIND
    ]
    assert len(found) == 1
    assert found[0].priority == 100
    assert found[0].source == "first-party"
    assert found[0].impl.impl is cls


def test_environment_decorator_defaults_and_bare_form(
    process_registry: ExtensionRegistry,
) -> None:
    @environment_plugin
    class Bare(BaseEnvironment):
        kind = "decorator-env-bare"
        capabilities = EnvironmentCapabilities()
        python_command = ("python3",)

        async def preflight(self) -> None:
            return None

        async def start(self, *, force_build: bool = False) -> None:
            del force_build

        async def stop(self, *, delete: bool) -> None:
            del delete

        def placement(self) -> Placement:
            return Placement(target_id="bare")

        def visible_path(self, box_path: str) -> str:
            return box_path

    row = _row(process_registry, ENVIRONMENT, "decorator-env-bare")
    assert row is not None
    assert row.impl is Bare
    assert row.priority == 100
    assert row.source == "first-party"
    assert row.is_factory is True


def test_executor_class_is_an_exclusive_candidate(process_registry: ExtensionRegistry) -> None:
    cls = executor_plugin(priority=120, source="first-party")(_executor_type())
    row = _row(process_registry, EXECUTOR, _EXEC_KIND)
    assert row is not None
    assert row.impl is cls
    assert row.priority == 120
    assert row.source == "first-party"
    assert row.is_factory is True
    assert row.impl.extra_allowlist == frozenset({"provider"})
    assert row.impl.requires_environment is False
    found = [item for item in process_registry.candidates(EXECUTOR) if item.plugin_id == _EXEC_KIND]
    assert len(found) == 1
    assert found[0].impl.impl is cls
    assert "consumes_model" not in cls.__dict__


@pytest.mark.parametrize("allowlist", [frozenset(), frozenset({"provider"})])
def test_declared_extra_allowlist_registers(
    process_registry: ExtensionRegistry,
    allowlist: frozenset[str],
) -> None:
    cls = executor_plugin()(_executor_type(extra_allowlist=allowlist))
    row = _row(process_registry, EXECUTOR, _EXEC_KIND)
    assert row is not None
    assert row.impl is cls
    assert row.impl.extra_allowlist == allowlist


def test_same_kind_overwrites_its_own_row(process_registry: ExtensionRegistry) -> None:
    environment_plugin(priority=100, source="first-party")(_environment_type())
    second = environment_plugin(priority=90, source="installed")(_environment_type())
    row = _row(process_registry, ENVIRONMENT, _ENV_KIND)
    assert row is not None
    assert row.impl is second
    assert row.priority == 90
    assert row.source == "installed"
    matched = [
        item for item in process_registry.candidates(ENVIRONMENT) if item.plugin_id == _ENV_KIND
    ]
    assert len(matched) == 1


def test_capability_flags_without_methods_still_register(
    process_registry: ExtensionRegistry,
) -> None:
    cls = environment_plugin()(
        _environment_type(
            capabilities=EnvironmentCapabilities(uid_gid=True, path_views=True, compose=True),
            omit={"exec", "upload", "download", "attach_stdio"},
        )
    )
    row = _row(process_registry, ENVIRONMENT, _ENV_KIND)
    assert row is not None
    assert row.impl is cls


def test_inherited_extra_allowlist_counts_as_declared(
    process_registry: ExtensionRegistry,
) -> None:
    parent = _executor_type("decorator-exec-parent", extra_allowlist=frozenset())

    @executor_plugin(priority=100, source="first-party")
    class Child(parent):  # type: ignore[misc]
        kind = "decorator-exec-child"

    row = _row(process_registry, EXECUTOR, "decorator-exec-child")
    assert row is not None
    assert row.impl is Child
    assert row.impl.extra_allowlist == frozenset()
    assert _row(process_registry, EXECUTOR, "decorator-exec-parent") is None


def test_not_a_subclass_is_a_contract_error(process_registry: ExtensionRegistry) -> None:
    class Plain:
        kind = "decorator-plain"

    with pytest.raises(PluginContractError, match="not a subclass of BaseEnvironment") as env_err:
        environment_plugin(priority=100, source="first-party")(cast(Any, Plain))

    assert env_err.value.kind == "plugin_contract"
    assert isinstance(env_err.value, ExtensionRegistryError)
    assert _row(process_registry, ENVIRONMENT, "decorator-plain") is None

    with pytest.raises(PluginContractError, match="not a subclass of BaseEnvironment"):
        environment_plugin()(cast(Any, _executor_type("decorator-wrong-base")))
    assert _row(process_registry, ENVIRONMENT, "decorator-wrong-base") is None

    with pytest.raises(PluginContractError, match="not a subclass of BaseExecutor"):
        executor_plugin()(cast(Any, _environment_type("decorator-wrong-exec")))
    assert _row(process_registry, EXECUTOR, "decorator-wrong-exec") is None
    assert _row(process_registry, ENVIRONMENT, "decorator-wrong-exec") is None


@pytest.mark.parametrize("method_name", ["preflight", "start", "stop"])
def test_missing_lifecycle_method_fails_registration(
    process_registry: ExtensionRegistry,
    method_name: str,
) -> None:
    cls = _environment_type(omit={method_name})
    with pytest.raises(PluginContractError, match=f"missing callable {method_name}"):
        environment_plugin()(cls)
    assert _row(process_registry, ENVIRONMENT, _ENV_KIND) is None


@pytest.mark.parametrize("cap", ["exec", "upload", "download", "attach_stdio"])
def test_capability_without_method_fails_registration(
    process_registry: ExtensionRegistry,
    cap: str,
) -> None:
    cls = _environment_type(
        capabilities=EnvironmentCapabilities(**{cap: True}),
        omit={cap},
    )
    with pytest.raises(PluginContractError, match=f"capabilities.{cap} is true"):
        environment_plugin()(cls)
    assert _row(process_registry, ENVIRONMENT, _ENV_KIND) is None


def test_capability_with_non_callable_fails_registration(
    process_registry: ExtensionRegistry,
) -> None:
    cls = _environment_type(capabilities=EnvironmentCapabilities(exec=True), exec="nope")
    with pytest.raises(
        PluginContractError, match="capabilities.exec is true but exec is not callable"
    ):
        environment_plugin()(cls)
    assert _row(process_registry, ENVIRONMENT, _ENV_KIND) is None


@pytest.mark.parametrize("method_name", ["invoke", "close", "supports_model", "bind_model"])
def test_missing_executor_method_fails_registration(
    process_registry: ExtensionRegistry,
    method_name: str,
) -> None:
    cls = _executor_type(omit={method_name})
    with pytest.raises(PluginContractError, match=f"missing callable {method_name}"):
        executor_plugin()(cls)
    assert _row(process_registry, EXECUTOR, _EXEC_KIND) is None


def test_missing_extra_allowlist_fails_registration(
    process_registry: ExtensionRegistry,
) -> None:
    with pytest.raises(PluginContractError, match="does not declare extra_allowlist") as caught:

        @executor_plugin(priority=100, source="first-party")
        class Broken(BaseExecutor):
            kind = "decorator-broken"
            requires_environment = False
            supported_apis = frozenset({"chat"})
            supported_model_fields = frozenset({"id", "api"})

            def supports_model(self, spec: Any) -> None:
                del spec

            def bind_model(self, spec: Any) -> None:
                del spec

            def invoke(self, prompt: str, **kwargs: Any) -> str:
                del kwargs
                return prompt

            def close(self) -> None:
                return None

    assert caught.value.kind == "plugin_contract"
    assert _row(process_registry, EXECUTOR, "decorator-broken") is None


@pytest.mark.parametrize("name", ["supported_apis", "supported_model_fields", "extra_allowlist"])
def test_undeclared_executor_set_fails_registration(
    process_registry: ExtensionRegistry,
    name: str,
) -> None:
    cls = _executor_type(omit={name})
    with pytest.raises(PluginContractError, match=f"does not declare {name}"):
        executor_plugin()(cls)
    assert _row(process_registry, EXECUTOR, _EXEC_KIND) is None


@pytest.mark.parametrize("name", ["supported_apis", "supported_model_fields", "extra_allowlist"])
def test_non_frozenset_metadata_fails_registration(
    process_registry: ExtensionRegistry,
    name: str,
) -> None:
    cls = _executor_type()
    setattr(cls, name, {"chat"})
    with pytest.raises(PluginContractError, match=f"{name} must be a frozenset of str"):
        executor_plugin()(cls)
    assert _row(process_registry, EXECUTOR, _EXEC_KIND) is None


def test_missing_kind_and_capabilities_fail_registration(
    process_registry: ExtensionRegistry,
) -> None:
    with pytest.raises(PluginContractError, match="does not declare kind"):
        environment_plugin()(_environment_type(omit={"kind"}))
    assert _row(process_registry, ENVIRONMENT, _ENV_KIND) is None

    with pytest.raises(PluginContractError, match="does not declare capabilities"):
        environment_plugin()(_environment_type(omit={"capabilities"}))
    assert _row(process_registry, ENVIRONMENT, _ENV_KIND) is None

    with pytest.raises(PluginContractError, match="does not declare kind"):
        executor_plugin()(_executor_type(omit={"kind"}))
    assert _row(process_registry, EXECUTOR, _EXEC_KIND) is None


def test_capabilities_must_be_an_instance(process_registry: ExtensionRegistry) -> None:
    cls = _environment_type()
    cls.capabilities = EnvironmentCapabilities  # type: ignore[assignment]
    with pytest.raises(
        PluginContractError, match="capabilities must be an EnvironmentCapabilities"
    ):
        environment_plugin()(cls)
    assert _row(process_registry, ENVIRONMENT, _ENV_KIND) is None


def test_requires_environment_must_be_a_bool(process_registry: ExtensionRegistry) -> None:
    cls = _executor_type(requires_environment="no")
    with pytest.raises(PluginContractError, match="requires_environment must be a bool"):
        executor_plugin()(cls)
    assert _row(process_registry, EXECUTOR, _EXEC_KIND) is None


def test_blank_kind_fails_registration(process_registry: ExtensionRegistry) -> None:
    with pytest.raises(PluginContractError, match="kind must be a non-empty string"):
        executor_plugin()(_executor_type(kind="  "))
    assert _row(process_registry, EXECUTOR, "  ") is None
