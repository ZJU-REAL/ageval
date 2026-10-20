"""Frozen options for the OpenHands executor."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field
from openhands_plugin.pin import SDK_VERSION

_PIN = re.compile(r"^\d+\.\d+\.\d+$")
_DEFAULT_MAX_ITERATIONS = 40


def parse_version(raw: Any) -> str:
    """Exact ``X.Y.Z`` pin. Omit uses the packaged pin. Ranges are rejected."""
    if raw is None or raw == "":
        return SDK_VERSION
    if isinstance(raw, str) and _PIN.fullmatch(raw.strip()):
        return raw.strip()
    raise ConfigError(
        ERROR_INVALID_SCHEMA,
        f"openhands_version_invalid:{raw!r}",
        location="options/version",
    )


def parse_max_iterations(raw: Any) -> int:
    if raw is None or raw == "":
        return _DEFAULT_MAX_ITERATIONS
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"openhands_max_iterations_invalid:{raw!r}",
            location="options/max_iterations",
        )
    return raw


@dataclass(frozen=True, slots=True)
class OpenHandsOptions:
    """Profile ``options`` for ``executor: openhands``."""

    version: str = field(
        default=SDK_VERSION,
        metadata={
            "type_name": "str",
            "parse": parse_version,
            "description": (
                "Exact openhands-sdk and openhands-tools version (X.Y.Z). "
                "Omit uses the packaged pin. Ranges, blanks, and non-pins are rejected."
            ),
        },
    )
    max_iterations: int = field(
        default=_DEFAULT_MAX_ITERATIONS,
        metadata={
            "type_name": "int",
            "parse": parse_max_iterations,
            "description": (
                "Cap on SDK iterations for one invoke. "
                "A non-positive value, bool, or non-integer is rejected."
            ),
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> OpenHandsOptions:
        return parse_options(cls, raw, location=location)


__all__ = ["OpenHandsOptions"]
