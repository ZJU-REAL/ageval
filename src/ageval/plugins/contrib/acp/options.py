"""Frozen options for the acp executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_idle, parse_options, stall_field


def parse_entry(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    raise ConfigError(ERROR_INVALID_SCHEMA, "acp_entry_required", location="options/entry")


@dataclass(frozen=True, slots=True)
class AcpOptions:
    """Profile ``options`` for ``executor: acp``."""

    entry: str = field(
        default="",
        metadata={
            "type_name": "str",
            "required": True,
            "missing": "acp_entry_required",
            "parse": parse_entry,
            "description": (
                "ACP entry id. Shipped: codex, claude-code, pi, opencode, grok-build. "
                "Missing fails lock with acp_entry_required."
            ),
        },
    )
    idle_timeout_seconds: float | None = field(
        default=None,
        metadata={
            "type_name": "float | unset",
            "clock": "idle_timeout",
            "parse": parse_idle,
            "description": (
                "Stall ceiling during session/prompt. Any session_update or "
                "request_permission resets it. Unset or a non-positive value leaves "
                "only the wall-clock invoke timeout. Fires acp_idle_timeout. "
                "Non-numeric fails lock with acp_idle_timeout_invalid."
            ),
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> AcpOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["AcpOptions"]
