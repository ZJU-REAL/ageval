"""Frozen options for the miniswe executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field


def _invalid(name: str, raw: Any) -> ConfigError:
    return ConfigError(
        ERROR_INVALID_SCHEMA,
        f"miniswe_{name}_invalid:{raw!r}",
        location=f"options/{name}",
    )


def parse_limit_int(name: str, default: int):
    def parse(raw: Any) -> int:
        if raw is None or raw == "":
            return default
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            raise _invalid(name, raw)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise _invalid(name, raw) from exc
        if value < 0:
            raise _invalid(name, raw)
        return value

    return parse


def parse_cost(raw: Any) -> float:
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise _invalid("cost_limit", raw)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise _invalid("cost_limit", raw) from exc
    if value < 0:
        raise _invalid("cost_limit", raw)
    return value


def parse_stream(raw: Any) -> bool:
    if raw is None or raw == "":
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off"}:
            return False
    raise _invalid("stream", raw)


@dataclass(frozen=True, slots=True)
class MinisweOptions:
    """Profile ``options`` for ``executor: miniswe``."""

    stream: bool = field(
        default=True,
        metadata={
            "type_name": "bool",
            "parse": parse_stream,
            "default_label": "`true` on `api: chat`",
            "description": (
                "Chat Completions use SSE when true. false sends one JSON body. "
                "An omitted key is true, so AGEVAL_MINISWE_CHAT_STREAM=0 does not "
                "turn a profile run off. Responses ignores this."
            ),
        },
    )
    step_limit: int = field(
        default=30,
        metadata={
            "type_name": "int",
            "parse": parse_limit_int("step_limit", 30),
            "description": "Agent step cap. 0 is unlimited. Negative values are rejected.",
        },
    )
    cost_limit: float = field(
        default=0.0,
        metadata={
            "type_name": "float",
            "parse": parse_cost,
            "description": "Cost cap. 0 is unlimited. Negative values are rejected.",
        },
    )
    cmd_timeout: int = field(
        default=30,
        metadata={
            "type_name": "int",
            "parse": parse_limit_int("cmd_timeout", 30),
            "description": "Seconds per host.exec bash action. Negative values are rejected.",
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> MinisweOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["MinisweOptions"]
