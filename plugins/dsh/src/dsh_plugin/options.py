"""Frozen options for the dsh executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.plugins.options import parse_options, stall_field

DEFAULT_COMPOSITION = "slim"
SANDBOXED_COMPOSITION = "sandboxed"
DEFAULT_PROVIDER = "deepseek-official"
PERMISSION_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})


def parse_composition(raw: Any) -> str:
    if raw is None or raw == "":
        return DEFAULT_COMPOSITION
    if not isinstance(raw, str):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"dsh_composition_invalid:{raw!r}",
            location="options/composition",
        )
    slug = raw.strip() or DEFAULT_COMPOSITION
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"dsh_composition_invalid:{slug}",
            location="options/composition",
        )
    return slug


def parse_permission(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"dsh_permission_invalid:{raw!r}",
            location="options/permission",
        )
    value = raw.strip()
    if not value:
        return None
    if value not in PERMISSION_MODES:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"dsh_permission_invalid:{value}",
            location="options/permission",
        )
    return value


def parse_max_tokens(raw: Any) -> int | None:
    """Omit / blank / null keeps the adapter default."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"dsh_max_tokens_invalid:{raw!r}",
            location="options/max_tokens",
        )
    return raw


def parse_provider(raw: Any) -> str:
    if raw is None or raw == "":
        return DEFAULT_PROVIDER
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            f"dsh_provider_invalid:{raw!r}",
            location="options/provider",
        )
    return raw.strip()


@dataclass(frozen=True, slots=True)
class DshOptions:
    """Profile ``options`` for ``executor: dsh``."""

    composition: str = field(
        default=DEFAULT_COMPOSITION,
        metadata={
            "type_name": "str",
            "parse": parse_composition,
            "description": (
                "Bundled compositions/<name>.cordis.yml. Path separators and a leading "
                "dot are rejected. Setting permission with omit or slim switches to sandboxed."
            ),
        },
    )
    permission: str | None = field(
        default=None,
        metadata={
            "type_name": "str | unset",
            "parse": parse_permission,
            "description": (
                "read-only, workspace-write, or danger-full-access. Omit keeps unrestricted "
                "slim tools. Invalid values are rejected. Sets DSH_PERMISSION_MODE. "
                "File-tool writes are fenced; bash redirect can still write."
            ),
        },
    )
    max_tokens: int | None = field(
        default=None,
        metadata={
            "type_name": "int | unset",
            "parse": parse_max_tokens,
            "description": (
                "Omit, blank, or null does not pass max_tokens. A positive int is forwarded. "
                "A non-positive int, bool, string, or float is rejected."
            ),
        },
    )
    provider: str = field(
        default=DEFAULT_PROVIDER,
        metadata={
            "type_name": "str",
            "parse": parse_provider,
            "description": "Provider id on initialize.",
        },
    )
    upstream_stall_seconds: int = stall_field()

    @classmethod
    def parse(cls, raw: object, *, location: str = "options") -> DshOptions:
        return parse_options(cls, raw, location=location)


__all__ = [
    "DEFAULT_COMPOSITION",
    "DEFAULT_PROVIDER",
    "DshOptions",
    "PERMISSION_MODES",
    "SANDBOXED_COMPOSITION",
    "parse_max_tokens",
    "parse_permission",
]
