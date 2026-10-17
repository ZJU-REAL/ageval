"""Frozen executor ``Options``. Lock rejects unknown keys.

Each ``@executor_plugin`` class sets ``Options`` to a frozen dataclass.
``parse`` is the only reader. A typo names the bad field and, when one name
is close, the nearest known field. Defaults that come from a clock row read
``CLOCKS`` so a table and a timeout cannot drift apart.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.runtime.clocks import CLOCKS, DISABLED, ClockError, Disabled, clock_default, parse_clock

Parse = Callable[[Any], Any]


def stall_default() -> int:
    """Omitted stall budget. ``0`` is the disabled value of this clock."""
    return int(clock_default("upstream_stall"))


def parse_stall(raw: Any) -> int:
    """``upstream_stall_seconds``. Omitted is the clock default. ``0`` disables."""
    from ageval.config.profiles import require_upstream_stall_seconds

    if raw is None or raw == "":
        return stall_default()
    value = require_upstream_stall_seconds(raw, location="options/upstream_stall_seconds")
    parsed = parse_clock("upstream_stall", value)
    if isinstance(parsed, Disabled):
        return 0
    return int(parsed)


def stall_field() -> Any:
    """Dataclass field for ``upstream_stall_seconds``. The clock table owns the default."""
    return dataclasses.field(
        default_factory=stall_default,
        metadata={
            "type_name": "int",
            "clock": "upstream_stall",
            "parse": parse_stall,
            "description": (
                "Parent stall budget in seconds. Omit uses the upstream_stall clock. "
                "0 disables. A negative value or a non-integer is rejected."
            ),
        },
    )


def suggest_name(bad: str, known: Sequence[str]) -> str | None:
    """Nearest known field when the edit distance is a typo, not a different word."""
    best: str | None = None
    best_distance: int | None = None
    for name in known:
        if name == bad:
            return name
        distance = _levenshtein(bad, name)
        limit = 3 if max(len(bad), len(name)) >= 8 else 1
        if distance > limit:
            continue
        if best_distance is None or distance < best_distance:
            best = name
            best_distance = distance
    return best


def parse_options(
    cls: type[Any],
    raw: Any,
    *,
    location: str = "options",
    enforce_required: bool = True,
) -> Any:
    """Build ``cls`` from a mapping. An instance of ``cls`` is returned as-is."""
    if isinstance(raw, cls):
        return raw
    if raw is None:
        data: dict[str, Any] = {}
    elif isinstance(raw, Mapping):
        data = {str(key): value for key, value in raw.items()}
    else:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"options must be a mapping, got {type(raw).__name__}",
            location=location,
        )
    known = {item.name: item for item in dataclasses.fields(cls)}
    unknown = [key for key in data if key not in known]
    if unknown:
        rendered: list[str] = []
        for key in unknown:
            hint = suggest_name(key, tuple(known))
            if hint:
                rendered.append(f"{key!r} (did you mean {hint!r}?)")
            else:
                rendered.append(repr(key))
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "unknown option " + ", ".join(rendered),
            location=location,
        )
    kwargs: dict[str, Any] = {}
    for name, item in known.items():
        if name not in data:
            continue
        parser: Parse | None = item.metadata.get("parse")
        kwargs[name] = parser(data[name]) if parser is not None else data[name]
    value = cls(**kwargs)
    if enforce_required:
        for name, item in known.items():
            if not item.metadata.get("required"):
                continue
            found = getattr(value, name)
            if found is None or (isinstance(found, str) and not found.strip()):
                message = str(item.metadata.get("missing") or f"{name} is required")
                raise ConfigError(ERROR_INVALID_SCHEMA, message, location=f"{location}/{name}")
    return value


def coerce_options(cls: type[Any], raw: Any, *, enforce_required: bool = True) -> Any:
    """Parse for an executor constructor.

    Lock calls ``parse`` and surfaces ``ConfigError``. A constructor wraps that
    as a materialize failure so a bad knob still fails before invoke.
    """
    from ageval.plugins.errors import ExtensionMaterializeError

    try:
        return parse_options(cls, raw, enforce_required=enforce_required)
    except ConfigError as exc:
        raise ExtensionMaterializeError(
            exc.message,
            kind="extension_materialize_failed",
        ) from exc


def mapping_for_model(raw: Any) -> dict[str, Any]:
    """Profile options as a mapping for the flat-model-key check.

    An already parsed ``Options`` instance has no flat model keys left.
    """
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def shown_default(item: dataclasses.Field[Any]) -> str:
    """Default cell for a generated parameter table."""
    label = item.metadata.get("default_label")
    if isinstance(label, str) and label:
        return label
    if item.metadata.get("required"):
        return "*(required)*"
    clock = item.metadata.get("clock")
    if isinstance(clock, str) and clock in CLOCKS:
        value = CLOCKS[clock].default
        if value is DISABLED:
            return "unset"
        return _show(value)
    if item.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        value = item.default_factory()
    elif item.default is not dataclasses.MISSING:
        value = item.default
    else:
        return "unset"
    return _show(value)


def render_param_table(options_cls: type[Any]) -> str:
    """Markdown table of one ``Options`` class. The header is stable."""
    lines = [
        "| Name | Default | Purpose |",
        "| --- | --- | --- |",
    ]
    for item in dataclasses.fields(options_cls):
        description = str(item.metadata.get("description") or "").replace("\n", " ")
        lines.append(f"| `options.{item.name}` | {shown_default(item)} | {description} |")
    return "\n".join(lines) + "\n"


def stall_budget_raw(binder: Any, row: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
    """Stall budget for one profile.

    A ``BaseExecutor`` with ``Options`` is parsed. Anything else reads the key
    only when the profile set it, so a scripted bag can carry other keys.
    """
    from ageval.plugins.base import BaseExecutor
    from ageval.plugins.slots import EXECUTOR

    plugin_id = str(row.get("executor") or "").strip()
    registry = getattr(binder, "registry", None)
    impl = None
    if registry is not None and plugin_id:
        registration = registry.get_registration(EXECUTOR, plugin_id)
        if registration is not None:
            impl = registration.impl
    options_cls = getattr(impl, "Options", None) if isinstance(impl, type) else None
    if isinstance(impl, type) and issubclass(impl, BaseExecutor) and isinstance(options_cls, type):
        return parse_options(options_cls, options).upstream_stall_seconds
    if "upstream_stall_seconds" in options:
        return options["upstream_stall_seconds"]
    return None


def assert_profile_options(
    profile: Mapping[str, Any],
    graph: Any,
    registry: Any,
    *,
    location: str,
) -> None:
    """Reject unknown executor options before the lock is written.

    A ``BaseExecutor`` winner parses with its ``Options`` class. A yaml-only
    factory has no schema; the model-contract warning covers that path until
    the third-party cutoff.
    """
    from ageval.config.profiles import executor_plugin_options
    from ageval.plugins.base import BaseExecutor

    winner = graph.winners.get("executor")
    if winner is None:
        return
    registration = registry.get_registration("executor", winner.plugin_id)
    impl = registration.impl if registration is not None else winner.impl
    if not isinstance(impl, type) or not issubclass(impl, BaseExecutor):
        return
    options_cls = getattr(impl, "Options", None)
    if not isinstance(options_cls, type):
        return
    parse_options(
        options_cls,
        executor_plugin_options(profile),
        location=f"{location}/options",
    )


def _show(value: Any) -> str:
    if value is None or value is DISABLED:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, start=1):
        current = [index]
        for other_index, other in enumerate(right, start=1):
            insert = current[other_index - 1] + 1
            delete = previous[other_index] + 1
            replace = previous[other_index - 1] + (char != other)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def _clock_error(message: str) -> ConfigError:
    return ConfigError(ERROR_INVALID_SCHEMA, message, location="options")


def parse_idle(raw: Any) -> float | None:
    """ACP idle ceiling. Unset or a non-positive value disables. Garbage fails."""
    if raw is None or raw == "":
        return None
    try:
        parsed = parse_clock("idle_timeout", raw)
    except ClockError as exc:
        raise _clock_error("acp_idle_timeout_invalid") from exc
    if isinstance(parsed, Disabled):
        return None
    return float(parsed)


__all__ = [
    "assert_profile_options",
    "coerce_options",
    "mapping_for_model",
    "parse_idle",
    "parse_options",
    "parse_stall",
    "render_param_table",
    "shown_default",
    "stall_default",
    "stall_field",
    "suggest_name",
]
