"""Frozen options for the anthropic-http executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field

_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_VERSION = "2023-06-01"


def parse_max_tokens(raw: Any) -> int:
    if raw is None or raw == "":
        return _DEFAULT_MAX_TOKENS
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "anthropic_max_tokens_invalid",
            location="options/max_tokens",
        )
    return raw


def parse_version(raw: Any) -> str:
    if raw is None or raw == "":
        return _DEFAULT_VERSION
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "anthropic_version_invalid",
            location="options/anthropic_version",
        )
    return raw.strip()


@dataclass(frozen=True, slots=True)
class AnthropicHTTPOptions:
    """Profile ``options`` for ``executor: anthropic-http``."""

    max_tokens: int = field(
        default=_DEFAULT_MAX_TOKENS,
        metadata={
            "type_name": "int",
            "parse": parse_max_tokens,
            "description": (
                "Required Messages max_tokens. Positive int. Non-int values are rejected."
            ),
        },
    )
    anthropic_version: str = field(
        default=_DEFAULT_VERSION,
        metadata={
            "type_name": "str",
            "parse": parse_version,
            "description": "anthropic-version request header. Non-string values are rejected.",
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> AnthropicHTTPOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["AnthropicHTTPOptions"]
