"""Register an environment or executor class on the process extension registry.

``@environment_plugin`` and ``@executor_plugin`` check the class, then call
``ExtensionRegistry.exclusive`` on ``get_global_registry``. They do not keep
a second candidate table. Importing a decorated class is what registers it.

``extra_allowlist`` has no default. An explicit empty ``frozenset`` is valid
and means lock rejects every extra key. ``uid_gid`` / ``path_views`` /
``compose`` are capability flags with no method. ``placement``,
``visible_path``, and ``python_command`` are not registration checks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, overload

from ageval.environments.protocol import EnvironmentCapabilities
from ageval.plugins.base import BaseEnvironment, BaseExecutor
from ageval.plugins.errors import PluginContractError
from ageval.plugins.registry import get_global_registry
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

_MISSING = object()
_LIFECYCLE_METHODS = ("preflight", "start", "stop")
_CAPABILITY_METHODS = ("exec", "upload", "download", "attach_stdio")
_EXECUTOR_METHODS = ("supports_model", "bind_model", "invoke", "close")
_EXECUTOR_SETS = ("supported_apis", "supported_model_fields", "extra_allowlist")


def _find(cls: type, name: str) -> Any:
    for klass in cls.__mro__:
        if name in klass.__dict__:
            return klass.__dict__[name]
    return _MISSING


def _require_subclass(cls: Any, base: type[Any], label: str) -> None:
    if isinstance(cls, type) and issubclass(cls, base):
        return
    name = getattr(cls, "__name__", repr(cls))
    raise PluginContractError(f"{name} is not a subclass of {label}")


def _require_declared(cls: type, name: str) -> Any:
    value = _find(cls, name)
    if value is _MISSING:
        raise PluginContractError(f"{cls.__name__} does not declare {name}")
    return value


def _has_callable(cls: type, name: str) -> bool:
    for klass in cls.__mro__:
        if name in klass.__dict__:
            value = klass.__dict__[name]
            if getattr(value, "__isabstractmethod__", False):
                return False
            return callable(getattr(cls, name, None))
    return False


def _require_callable(cls: type, name: str) -> None:
    if not _has_callable(cls, name):
        raise PluginContractError(f"{cls.__name__} is missing callable {name}")


def _require_kind(cls: type) -> str:
    kind = _require_declared(cls, "kind")
    if not isinstance(kind, str) or not kind.strip():
        raise PluginContractError(f"{cls.__name__} kind must be a non-empty string")
    return kind


def _require_frozenset(cls: type, name: str) -> None:
    value = _require_declared(cls, name)
    if type(value) is not frozenset or any(not isinstance(item, str) for item in value):
        raise PluginContractError(f"{cls.__name__} {name} must be a frozenset of str")


def _register_environment(
    cls: type,
    *,
    priority: int,
    source: str,
) -> None:
    _require_subclass(cls, BaseEnvironment, "BaseEnvironment")
    kind = _require_kind(cls)
    capabilities = _require_declared(cls, "capabilities")
    if not isinstance(capabilities, EnvironmentCapabilities):
        raise PluginContractError(
            f"{cls.__name__} capabilities must be an EnvironmentCapabilities instance"
        )
    for name in _LIFECYCLE_METHODS:
        _require_callable(cls, name)
    for name in _CAPABILITY_METHODS:
        if getattr(capabilities, name) and not _has_callable(cls, name):
            raise PluginContractError(
                f"{cls.__name__} capabilities.{name} is true but {name} is not callable"
            )
    get_global_registry().exclusive(
        ENVIRONMENT,
        kind,
        cls,
        priority=priority,
        source=source,
        is_factory=True,
    )


def _register_executor(
    cls: type,
    *,
    priority: int,
    source: str,
) -> None:
    _require_subclass(cls, BaseExecutor, "BaseExecutor")
    kind = _require_kind(cls)
    requires_environment = _require_declared(cls, "requires_environment")
    if not isinstance(requires_environment, bool):
        raise PluginContractError(f"{cls.__name__} requires_environment must be a bool")
    for name in _EXECUTOR_SETS:
        _require_frozenset(cls, name)
    for name in _EXECUTOR_METHODS:
        _require_callable(cls, name)
    get_global_registry().exclusive(
        EXECUTOR,
        kind,
        cls,
        priority=priority,
        source=source,
        is_factory=True,
    )


@overload
def environment_plugin[EnvT: BaseEnvironment](cls: type[EnvT], /) -> type[EnvT]: ...


@overload
def environment_plugin[EnvT: BaseEnvironment](
    *,
    priority: int = ...,
    source: str = ...,
) -> Callable[[type[EnvT]], type[EnvT]]: ...


def environment_plugin(
    cls: type[BaseEnvironment] | None = None,
    /,
    *,
    priority: int = 100,
    source: str = "first-party",
) -> Any:
    """Register a ``BaseEnvironment`` subclass on the process exclusive table.

    ``priority`` defaults to 100. ``source`` defaults to ``first-party``.
    ``kind`` and ``capabilities`` come from the class.
    """

    def decorate(target: type[BaseEnvironment]) -> type[BaseEnvironment]:
        _register_environment(target, priority=priority, source=source)
        return target

    if cls is None:
        return decorate
    return decorate(cls)


@overload
def executor_plugin[ExecT: BaseExecutor](cls: type[ExecT], /) -> type[ExecT]: ...


@overload
def executor_plugin[ExecT: BaseExecutor](
    *,
    priority: int = ...,
    source: str = ...,
) -> Callable[[type[ExecT]], type[ExecT]]: ...


def executor_plugin(
    cls: type[BaseExecutor] | None = None,
    /,
    *,
    priority: int = 100,
    source: str = "first-party",
) -> Any:
    """Register a ``BaseExecutor`` subclass on the process exclusive table.

    ``priority`` defaults to 100. ``source`` defaults to ``first-party``.
    ``kind`` comes from the class. ``extra_allowlist`` must be declared.
    """

    def decorate(target: type[BaseExecutor]) -> type[BaseExecutor]:
        _register_executor(target, priority=priority, source=source)
        return target

    if cls is None:
        return decorate
    return decorate(cls)


__all__ = ["environment_plugin", "executor_plugin"]
