"""The one place an exclusive slot winner becomes a live object.

Resolution (``resolve.py``) decides *which* plugin wins and puts that in the
lock. It deliberately does not construct anything: the box needs the Attempt
work root, the executor needs the started box, and neither exists at lock time.
Binding therefore happens here, once, with the engine-owned context passed in.
"""

from __future__ import annotations

from typing import Any

from ageval.config.errors import ConfigError
from ageval.model.errors import ModelConfigError
from ageval.plugins.base import BaseExecutor
from ageval.plugins.errors import ExtensionMaterializeError, ExtensionPluginNotFoundError
from ageval.plugins.options import parse_options
from ageval.plugins.protocol import ExtensionGraph
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.slots import EXECUTOR

# Factory id → accepted kwarg names (None = pass the whole context).
_accepted_names: dict[int, frozenset[str] | None] = {}


def _accepted(factory: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Pass only the context this factory declared; extras are not its business."""
    import inspect

    key = id(factory)
    if key not in _accepted_names:
        try:
            parameters = inspect.signature(factory).parameters
        except (TypeError, ValueError):
            _accepted_names[key] = None
        else:
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                _accepted_names[key] = None
            else:
                _accepted_names[key] = frozenset(parameters)
    names = _accepted_names[key]
    if names is None:
        return context
    return {name: value for name, value in context.items() if name in names}


def bind_winner(
    registry: ExtensionRegistry,
    graph: ExtensionGraph,
    slot: str,
    *,
    options: dict[str, Any] | None = None,
    **context: Any,
) -> Any:
    """Construct the winner of *slot* with engine-owned *context*."""
    winner = graph.winners.get(slot)
    if winner is None:
        raise ExtensionPluginNotFoundError(
            f"no plugin is bound to exclusive slot {slot!r}",
            kind="extension_plugin_not_found",
        )
    registration = registry.get_registration(slot, winner.plugin_id)
    if registration is None:
        raise ExtensionPluginNotFoundError(
            f"plugin {winner.plugin_id!r} no longer registers slot {slot!r}",
            kind="extension_plugin_not_found",
        )
    if not registration.is_factory:
        return registration.impl
    if not callable(registration.impl):
        raise ExtensionMaterializeError(
            f"factory for plugin {winner.plugin_id!r} slot {slot!r} is not callable",
            kind="extension_materialize_failed",
        )
    bound_options: Any = dict(winner.options or {}) if options is None else dict(options)
    impl = registration.impl
    options_cls = getattr(impl, "Options", None)
    if (
        slot == EXECUTOR
        and isinstance(impl, type)
        and issubclass(impl, BaseExecutor)
        and isinstance(options_cls, type)
    ):
        bound_options = parse_options(options_cls, bound_options)
    try:
        # Factories do not share one signature. ``options`` is always passed;
        # ``_accepted`` drops context keys the factory did not declare.
        # Call the registry attribute (typed Any). ``impl`` is narrowed to a
        # BaseExecutor subclass on the parse branch, and that class constructor
        # has no ``options`` parameter.
        return registration.impl(
            options=bound_options,
            **_accepted(registration.impl, context),
        )
    except (ExtensionMaterializeError, ModelConfigError, ConfigError):
        raise
    except Exception as exc:  # noqa: BLE001 — one bind failure, no retry
        raise ExtensionMaterializeError(
            f"bind failed for plugin {winner.plugin_id!r} slot {slot!r}: {exc}",
            kind="extension_materialize_failed",
        ) from exc
