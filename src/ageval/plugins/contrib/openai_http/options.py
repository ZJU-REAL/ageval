"""Frozen options for the openai-http executor."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field


def parse_max_tokens(raw: Any) -> int | None:
    """Omit, blank, or null does not send a token cap."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"openai_max_tokens_invalid:{raw!r}",
            location="options/max_tokens",
        )
    return raw


def parse_omit_temperature(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "omit_temperature_requires_bool",
            location="options/omit_temperature",
        )
    return value


def parse_stream(value: Any) -> bool:
    """``stream`` is a real boolean; ``1``/``"true"`` are lock errors."""
    if not isinstance(value, bool):
        raise ConfigError(ERROR_INVALID_SCHEMA, "stream_requires_bool", location="options/stream")
    return value


def parse_stream_seconds(value: Any) -> float | None:
    """Positive finite seconds. ``None`` disables the clock."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "stream_timeout_requires_positive_seconds",
            location="options",
        )
    return float(value)


@dataclass(frozen=True, slots=True)
class OpenAIHTTPOptions:
    """Profile ``options`` for ``executor: openai-http``.

    Model fields live on the nested ``model:`` object, not here.
    """

    max_tokens: int | None = field(
        default=None,
        metadata={
            "type_name": "int | unset",
            "parse": parse_max_tokens,
            "description": (
                "Omit, blank, or null does not pass a token cap. A positive int is "
                "max_tokens on api: chat and max_output_tokens on api: responses. "
                "A non-positive int, bool, string, or float is rejected."
            ),
        },
    )
    omit_temperature: bool = field(
        default=False,
        metadata={
            "type_name": "bool",
            "parse": parse_omit_temperature,
            "description": (
                "When true, do not send temperature. Default false keeps temperature 0 "
                "on api: chat. Responses does not send temperature."
            ),
        },
    )
    stream: bool = field(
        default=False,
        metadata={
            "type_name": "bool",
            "parse": parse_stream,
            "description": (
                "Opt-in native SSE for api: chat and api: responses. false keeps one JSON body."
            ),
        },
    )
    stream_first_event_timeout_seconds: float | None = field(
        default=None,
        metadata={
            "type_name": "float | None",
            "parse": parse_stream_seconds,
            "description": (
                "Deadline from request start to the first SSE data event. "
                "Comments and heartbeats do not satisfy it. Unset disables."
            ),
        },
    )
    stream_idle_timeout_seconds: float | None = field(
        default=None,
        metadata={
            "type_name": "float | None",
            "parse": parse_stream_seconds,
            "description": (
                "Deadline from the last meaningful text/thought/tool fragment. "
                "Heartbeats do not reset it. Unset disables."
            ),
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> OpenAIHTTPOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["OpenAIHTTPOptions"]
