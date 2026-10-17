"""One table of ageval clocks.

Readers take their numbers from ``CLOCKS``. A zero watchdog does not fall
back to 180, and a disabled timeout does not become that default either.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

ZeroPolicy = Literal["reject", "disabled", "fallback"]


class Disabled:
    """A clock that is off. It is not a number."""

    def __repr__(self) -> str:
        return "DISABLED"


DISABLED = Disabled()


class ClockError(ValueError):
    """A clock value is not allowed for that row."""


@dataclass(frozen=True, slots=True)
class Clock:
    name: str
    default: float | Disabled
    zero: ZeroPolicy
    readers: tuple[str, ...]
    integral: bool = False
    non_positive: bool = False
    stall_freezes_parent: bool = False


# ``non_positive`` applies the zero policy to every value <= 0.
# Otherwise only 0 uses that policy and a negative value is rejected.
CLOCKS: dict[str, Clock] = {
    "timeout": Clock(
        name="timeout",
        default=DISABLED,
        zero="disabled",
        readers=("model.spec",),
    ),
    "watchdog": Clock(
        name="watchdog",
        default=180.0,
        zero="reject",
        readers=("anthropic-http", "miniswe", "openai-http"),
    ),
    "upstream_stall": Clock(
        name="upstream_stall",
        default=3600.0,
        zero="disabled",
        readers=("runtime.upstream_stall",),
        integral=True,
        stall_freezes_parent=True,
    ),
    "stall_interval": Clock(
        name="stall_interval",
        default=60.0,
        zero="reject",
        readers=("runtime.upstream_stall",),
        integral=True,
    ),
    "idle_timeout": Clock(
        name="idle_timeout",
        default=DISABLED,
        zero="disabled",
        readers=("acp",),
        non_positive=True,
    ),
    "invoke_timeout": Clock(
        name="invoke_timeout",
        default=300.0,
        zero="fallback",
        readers=("runtime.parent_agent",),
        non_positive=True,
    ),
    "acp_home_cap": Clock(
        name="acp_home_cap",
        default=120.0,
        zero="reject",
        readers=("acp.executor", "acp.hooks"),
    ),
    "docker_build": Clock(
        name="docker_build",
        default=3600.0,
        zero="reject",
        readers=("docker.images",),
    ),
}


def parse_clock(name: str, raw: Any) -> float | Disabled:
    """Resolve one clock. Omitted raw uses the row default.

    ``0`` follows ``zero``. It never becomes another row's default.
    """
    clock = CLOCKS[name]
    if raw is None or raw == "":
        return clock.default
    value = _number(clock, raw)
    if value > 0:
        return value
    if value < 0 and not clock.non_positive:
        raise ClockError(f"{name}_invalid:{raw!r}")
    if clock.zero == "disabled":
        return DISABLED
    if clock.zero == "fallback":
        if isinstance(clock.default, Disabled):
            return DISABLED
        return float(clock.default)
    raise ClockError(f"{name}_invalid:{raw!r}")


def clock_default(name: str) -> float:
    """Numeric default of one row. A disabled default is an error."""
    value = CLOCKS[name].default
    if isinstance(value, Disabled):
        raise ClockError(f"{name}_invalid:disabled")
    return float(value)


def clock_seconds(name: str, raw: Any) -> float:
    """``parse_clock`` for a row that is always a number."""
    parsed = parse_clock(name, raw)
    if isinstance(parsed, Disabled):
        raise ClockError(f"{name}_invalid:{raw!r}")
    return parsed


def clocks_snapshot() -> dict[str, Any]:
    """JSON-ready dump. ``DISABLED`` is the string ``disabled``."""
    snapshot: dict[str, Any] = {}
    for name in sorted(CLOCKS):
        clock = CLOCKS[name]
        default: Any = "disabled" if clock.default is DISABLED else clock.default
        snapshot[name] = {
            "default": default,
            "zero": clock.zero,
            "integral": clock.integral,
            "non_positive": clock.non_positive,
            "stall_freezes_parent": clock.stall_freezes_parent,
            "readers": list(clock.readers),
        }
    return snapshot


def _number(clock: Clock, raw: Any) -> float:
    if isinstance(raw, bool):
        raise ClockError(f"{clock.name}_invalid:{raw!r}")
    if clock.integral:
        if type(raw) is not int:
            raise ClockError(f"{clock.name}_invalid:{raw!r}")
        return float(raw)
    if isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise ClockError(f"{clock.name}_invalid:{raw!r}") from exc
    elif isinstance(raw, int | float):
        value = float(raw)
    else:
        raise ClockError(f"{clock.name}_invalid:{raw!r}")
    if not math.isfinite(value):
        raise ClockError(f"{clock.name}_invalid:{raw!r}")
    return value
