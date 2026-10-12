"""Composition-root bootstrap for the extension registry.

Order: engine defaults → builtin environments → builtin executors → installed
plugin cache. Ecosystem plugins, including miniswe, load only after
``ageval plugin install``.
"""

from __future__ import annotations

from ageval.plugins.builtin import load_builtin_environments, load_builtin_executors
from ageval.plugins.defaults import register_defaults
from ageval.plugins.registry import ExtensionRegistry, get_global_registry, reset_global_registry

_BOOTSTRAPPED = False


def bootstrap_registry(
    registry: ExtensionRegistry | None = None,
    *,
    force: bool = False,
) -> ExtensionRegistry:
    """Ensure the process registry has engine + first-party contributions."""
    global _BOOTSTRAPPED
    reg = registry if registry is not None else get_global_registry()
    if registry is None and _BOOTSTRAPPED and not force:
        return reg
    if force and registry is None:
        reg = reset_global_registry()
    elif force and registry is not None:
        reg.clear()

    register_defaults(reg)
    load_builtin_environments(reg)
    load_builtin_executors(reg)

    from ageval.plugins.load_installed import load_installed_plugins

    load_installed_plugins(reg)

    if registry is None:
        _BOOTSTRAPPED = True
    return reg


def ensure_bootstrapped() -> ExtensionRegistry:
    return bootstrap_registry()
