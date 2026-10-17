"""Frozen options for the acp-oneshot executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field


def parse_entry(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    raise ConfigError(ERROR_INVALID_SCHEMA, "acp_entry_required", location="options/entry")


@dataclass(frozen=True, slots=True)
class AcpOneshotOptions:
    """Profile ``options`` for ``executor: acp-oneshot``."""

    entry: str = field(
        default="",
        metadata={
            "type_name": "str",
            "required": True,
            "missing": "acp_entry_required",
            "parse": parse_entry,
            "description": (
                "ACP entry id (codex, claude-code, pi, opencode, grok-build). "
                "Missing or unknown fails materialize."
            ),
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> AcpOneshotOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["AcpOneshotOptions"]
