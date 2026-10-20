"""Frozen options for the terminus-2 executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field


def _invalid(name: str, raw: Any) -> ConfigError:
    return ConfigError(
        ERROR_INVALID_SCHEMA,
        f"terminus2_{name}_invalid:{raw!r}",
        location=f"options/{name}",
    )


def _parse_int(name: str, default: int, *, minimum: int):
    def parse(raw: Any) -> int:
        if raw is None or raw == "":
            return default
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            raise _invalid(name, raw)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise _invalid(name, raw) from exc
        if value < minimum:
            raise _invalid(name, raw)
        return value

    return parse


def _parse_parser(raw: Any) -> str:
    if raw is None or raw == "":
        return "json"
    if not isinstance(raw, str):
        raise _invalid("parser", raw)
    name = raw.strip().lower()
    if name not in {"json", "xml"}:
        raise _invalid("parser", raw)
    return name


@dataclass(frozen=True, slots=True)
class Terminus2Options:
    """Profile ``options`` for ``executor: terminus-2``."""

    parser: str = field(
        default="json",
        metadata={
            "type_name": "str",
            "parse": _parse_parser,
            "description": "Command batch format: json or xml. Anything else is rejected.",
        },
    )
    step_limit: int = field(
        default=30,
        metadata={
            "type_name": "int",
            "parse": _parse_int("step_limit", 30, minimum=0),
            "description": "Model turns before the episode stops. 0 is unlimited.",
        },
    )
    cmd_timeout: int = field(
        default=60,
        metadata={
            "type_name": "int",
            "parse": _parse_int("cmd_timeout", 60, minimum=1),
            "description": "Seconds per environment.exec, including tmux install and pane capture.",
        },
    )
    pane_width: int = field(
        default=160,
        metadata={
            "type_name": "int",
            "parse": _parse_int("pane_width", 160, minimum=1),
            "description": "tmux pane width in columns.",
        },
    )
    pane_height: int = field(
        default=40,
        metadata={
            "type_name": "int",
            "parse": _parse_int("pane_height", 40, minimum=1),
            "description": "tmux pane height in rows.",
        },
    )
    max_format_errors: int = field(
        default=3,
        metadata={
            "type_name": "int",
            "parse": _parse_int("max_format_errors", 3, minimum=1),
            "description": "Malformed replies returned to the model before the episode stops.",
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> Terminus2Options:
        return parse_options(cls, raw, location=location)


__all__ = ["Terminus2Options"]
