"""Explicit builtin environment and executor modules (scheme A).

The tuples are the builtin set. ``load_builtin_*`` imports each listed module
so ``@environment_plugin`` / ``@executor_plugin`` register on the process
registry. Nothing walks ``contrib/`` or any other directory.

``miniswe`` is not a builtin executor. It enters only through
``load_installed_plugins`` (``plugins/miniswe``).

Until a listed class is itself the exclusive factory, the loader still calls
that module's ``register_*_contrib``. A class defined in the listed module is
left in place. ACP chain slots and the ``attach_stdio`` inject stay on
``register_acp_contrib`` either way.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

from ageval.plugins.registry import ExtensionRegistry, Registration, get_global_registry
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

_ACP_EXECUTOR_MODULE = "ageval.plugins.contrib.acp.executor"

# Authoritative builtin membership. Commenting out a line disables that contrib.
_BUILTIN_ENVIRONMENT_MODULES: tuple[str, ...] = (
    "ageval.plugins.contrib.local.host",
    "ageval.plugins.contrib.docker.host",
    "ageval.plugins.contrib.e2b.host",
    "ageval.plugins.contrib.daytona.host",
    "ageval.plugins.contrib.ssh.host",
)

_BUILTIN_EXECUTOR_MODULES: tuple[str, ...] = (
    "ageval.plugins.contrib.acp.executor",
    "ageval.plugins.contrib.openai_http.executor",
    "ageval.plugins.contrib.anthropic_http.executor",
)

# Temporary shims for contrib that does not yet decorate its class.
# Keyed by the module tuples above; a name absent from the tuple is not called.
_ENVIRONMENT_REGISTRARS: dict[str, str] = {
    "ageval.plugins.contrib.local.host": "ageval.plugins.contrib.local:register_local_contrib",
    "ageval.plugins.contrib.docker.host": "ageval.plugins.contrib.docker:register_docker_contrib",
    "ageval.plugins.contrib.e2b.host": "ageval.plugins.contrib.e2b:register_e2b_contrib",
    "ageval.plugins.contrib.daytona.host": (
        "ageval.plugins.contrib.daytona:register_daytona_contrib"
    ),
    "ageval.plugins.contrib.ssh.host": "ageval.plugins.contrib.ssh:register_ssh_contrib",
}

_EXECUTOR_REGISTRARS: dict[str, str] = {
    "ageval.plugins.contrib.acp.executor": "ageval.plugins.contrib.acp:register_acp_contrib",
    "ageval.plugins.contrib.openai_http.executor": (
        "ageval.plugins.contrib.openai_http:register_openai_http_contrib"
    ),
    "ageval.plugins.contrib.anthropic_http.executor": (
        "ageval.plugins.contrib.anthropic_http:register_anthropic_http_contrib"
    ),
}

_ENVIRONMENT_PLUGIN_IDS: dict[str, str] = {
    "ageval.plugins.contrib.local.host": "local",
    "ageval.plugins.contrib.docker.host": "docker",
    "ageval.plugins.contrib.e2b.host": "e2b",
    "ageval.plugins.contrib.daytona.host": "daytona",
    "ageval.plugins.contrib.ssh.host": "ssh",
}

_EXECUTOR_PLUGIN_IDS: dict[str, str] = {
    "ageval.plugins.contrib.acp.executor": "acp",
    "ageval.plugins.contrib.openai_http.executor": "openai-http",
    "ageval.plugins.contrib.anthropic_http.executor": "anthropic-http",
}

_Registrar = Callable[[ExtensionRegistry], None]


def load_builtin_environments(registry: ExtensionRegistry | None = None) -> None:
    """Import builtin environment modules and register any that the import did not."""
    _load(
        _BUILTIN_ENVIRONMENT_MODULES,
        _ENVIRONMENT_PLUGIN_IDS,
        _ENVIRONMENT_REGISTRARS,
        ENVIRONMENT,
        registry,
    )


def load_builtin_executors(registry: ExtensionRegistry | None = None) -> None:
    """Import builtin executor modules and register any that the import did not."""
    _load(
        _BUILTIN_EXECUTOR_MODULES,
        _EXECUTOR_PLUGIN_IDS,
        _EXECUTOR_REGISTRARS,
        EXECUTOR,
        registry,
    )


def _load(
    modules: tuple[str, ...],
    plugin_ids: dict[str, str],
    registrars: dict[str, str],
    slot: str,
    registry: ExtensionRegistry | None,
) -> None:
    target = registry if registry is not None else get_global_registry()
    for module_name in modules:
        importlib.import_module(module_name)
        plugin_id = plugin_ids[module_name]
        if _listed_class_owns(target, slot, plugin_id, module_name):
            if module_name == _ACP_EXECUTOR_MODULE:
                _register_acp_keeping_class(target)
            continue
        _call_registrar(registrars[module_name], target)


def _listed_class_owns(
    registry: ExtensionRegistry,
    slot: str,
    plugin_id: str,
    module_name: str,
) -> bool:
    """True when this registry's exclusive factory is a class from *module_name*.

    That is the decorator side effect (the class statement registered it).
    Today's ``register_*_contrib`` factories for executors are functions, so
    they do not take this path. Environment contrib already registers the
    class; a second load then leaves that row alone.
    """
    row = registry.get_registration(slot, plugin_id)
    if row is None or not isinstance(row.impl, type):
        return False
    return row.impl.__module__ == module_name


def _call_registrar(spec: str, registry: ExtensionRegistry) -> None:
    module_name, func_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    registrar: _Registrar = getattr(module, func_name)
    registrar(registry)


def _register_acp_keeping_class(registry: ExtensionRegistry) -> None:
    """Register ACP chains and inject without replacing a class factory."""
    saved = registry.get_registration(EXECUTOR, "acp")
    from ageval.plugins.contrib.acp import register_acp_contrib

    register_acp_contrib(registry)
    if saved is None or not isinstance(saved.impl, type):
        return
    _restore_exclusive(registry, saved)


def _restore_exclusive(registry: ExtensionRegistry, saved: Registration) -> None:
    registry.exclusive(
        saved.slot,
        saved.plugin_id,
        saved.impl,
        priority=saved.priority,
        source=saved.source,
        version=saved.version,
        digest=saved.digest,
        is_default=saved.is_default,
        is_factory=saved.is_factory,
    )
