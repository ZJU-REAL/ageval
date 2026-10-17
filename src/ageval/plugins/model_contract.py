"""Lock-time model contract. Runs after winners resolve, before the lock is written.

A ``BaseExecutor`` winner is checked here. ``supports_model`` raises
``ModelConfigError``. ``requires_environment`` that the bound environment
cannot meet raises ``PluginContractError``. Neither is an upstream stall.

A yaml-only executor is a factory that is not a ``BaseExecutor`` class, so it
cannot declare ``extra_allowlist``. With the env unset, a ``first-party``
registration fails the lock. Any other source warns until 2027-01-15.
On that date the warning becomes a hard reject, including when the env is
off. ``AGEVAL_STRICT_MODEL_CONTRACT`` set to ``1``, ``true``, ``yes``,
``on``, or ``strict`` raises ``PluginContractError``. ``0``, ``false``,
``no``, or ``off`` keeps the warning only before the cutoff.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from datetime import date
from typing import Any

from ageval.model.spec import resolve_model
from ageval.plugins.base import BaseExecutor
from ageval.plugins.errors import PluginContractError
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR

STRICT_MODEL_CONTRACT_ENV = "AGEVAL_STRICT_MODEL_CONTRACT"
_STRICT_VALUES = frozenset({"1", "true", "yes", "on", "strict"})
_OFF_VALUES = frozenset({"0", "false", "no", "off"})
_FIRST_PARTY = "first-party"
YAML_ONLY_CUTOFF = date(2027, 1, 15)


class YamlOnlyExecutorWarning(UserWarning):
    """Lock could not enforce an extra allowlist for this executor."""


def _today() -> date:
    """Clock for the yaml-only cutoff. Tests replace this."""
    return date.today()


def strict_model_contract(override: bool | None = None, *, source: str = "") -> bool:
    """True when a yaml-only executor must fail the lock.

    An explicit override wins. After 2027-01-15 every source fails, including
    when the env is off. Before that date the env forces on or off. Unset, a
    ``first-party`` registration fails and every other source warns.
    """
    if override is not None:
        return override
    if _today() >= YAML_ONLY_CUTOFF:
        return True
    raw = os.environ.get(STRICT_MODEL_CONTRACT_ENV, "").strip().lower()
    if raw in _STRICT_VALUES:
        return True
    if raw in _OFF_VALUES:
        return False
    return source == _FIRST_PARTY


def assert_requires_environment(graph: ExtensionGraph, registry: ExtensionRegistry) -> None:
    """Reject a class winner whose environment inject is missing or short on caps."""
    impl = _executor_impl(graph, registry)
    if impl is None or not impl.requires_environment:
        return
    winner = graph.winners[EXECUTOR]
    plugin_id = winner.plugin_id
    env = graph.winners.get(ENVIRONMENT)
    if env is None:
        raise PluginContractError(
            f"{plugin_id} requires_environment but no environment winner is bound"
        )
    rows = tuple(row for row in graph.injects.get(plugin_id, ()) if row.service == ENVIRONMENT)
    if not rows:
        raise PluginContractError(
            f"{plugin_id} requires_environment but does not inject service {ENVIRONMENT!r}"
        )
    caps = getattr(env.impl, "capabilities", None)
    if caps is None:
        raise PluginContractError(
            f"{plugin_id} requires_environment but environment {env.plugin_id!r} "
            "declares no capabilities"
        )
    missing: list[str] = []
    for row in rows:
        wanted = tuple(row.capabilities)
        if not wanted:
            raise PluginContractError(
                f"{plugin_id} requires_environment but injects {ENVIRONMENT!r} with no capabilities"
            )
        for name in _missing_caps(caps, wanted):
            if name not in missing:
                missing.append(name)
    if missing:
        raise PluginContractError(
            f"{plugin_id} requires_environment but environment {env.plugin_id!r} "
            f"does not provide {missing}"
        )


def assert_executor_model(
    profile: Mapping[str, Any],
    graph: ExtensionGraph,
    registry: ExtensionRegistry,
    *,
    strict: bool | None = None,
) -> None:
    """``resolve_model`` then ``supports_model`` for a class winner.

    Yaml-only winners warn, or raise ``PluginContractError`` when *strict*
    (or ``AGEVAL_STRICT_MODEL_CONTRACT``) is set. An omitted ``model`` on a
    class winner is not sent, so ``supports_model`` is skipped.
    """
    winner = graph.winners.get(EXECUTOR)
    if winner is None:
        return
    impl = _executor_impl(graph, registry)
    if impl is None:
        # An explicit profile binding rewrites the winner source to "explicit".
        # Strictness follows the registration row.
        registration = registry.get_registration(EXECUTOR, winner.plugin_id)
        source = registration.source if registration is not None else winner.source
        _yaml_only(winner.plugin_id, strict=strict, source=source)
        return
    model = profile.get("model")
    if not isinstance(model, Mapping):
        return
    from ageval.config.profiles import model_options

    spec = resolve_model(model, model_options(profile))
    impl.supports_model(spec)


def _executor_impl(graph: ExtensionGraph, registry: ExtensionRegistry) -> type[BaseExecutor] | None:
    winner = graph.winners.get(EXECUTOR)
    if winner is None:
        return None
    registration = registry.get_registration(EXECUTOR, winner.plugin_id)
    impl = registration.impl if registration is not None else winner.impl
    if isinstance(impl, type) and issubclass(impl, BaseExecutor):
        return impl
    return None


def _yaml_only(plugin_id: str, *, strict: bool | None, source: str) -> None:
    message = (
        f"executor {plugin_id!r} has no decorated model contract; extra allowlist is not enforced. "
        "Third-party yaml-only factories are rejected after 2027-01-15"
    )
    if strict_model_contract(strict, source=source):
        raise PluginContractError(message)
    warnings.warn(message, YamlOnlyExecutorWarning, stacklevel=3)


def _missing_caps(caps: Any, wanted: tuple[str, ...]) -> list[str]:
    return [str(name) for name in caps.missing(wanted)]
