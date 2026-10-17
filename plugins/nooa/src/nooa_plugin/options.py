"""Frozen options for the nooa executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field


def parse_agent(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    raise ConfigError(
        ERROR_INVALID_SCHEMA,
        "nooa_options_agent_required",
        location="options/agent",
    )


def parse_method(raw: Any) -> str:
    if raw is None or raw == "":
        return "run"
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"nooa_method_invalid:{raw!r}",
            location="options/method",
        )
    return raw.strip()


@dataclass(frozen=True, slots=True)
class NooaOptions:
    """Profile ``options`` for ``executor: nooa``."""

    agent: str = field(
        default="",
        metadata={
            "type_name": "str",
            "required": True,
            "missing": "nooa_options_agent_required",
            "parse": parse_agent,
            "description": (
                "Package-local module:Class (subclass nooa.Agent, or a deterministic "
                "class). Missing fails lock with nooa_options_agent_required."
            ),
        },
    )
    method: str = field(
        default="run",
        metadata={
            "type_name": "str",
            "parse": parse_method,
            "description": "Method invoked on that class.",
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> NooaOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["NooaOptions"]
