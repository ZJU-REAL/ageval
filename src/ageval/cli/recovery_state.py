"""Resolve whether a settled Attempt keeps its recovery bundle."""

from __future__ import annotations

from collections.abc import Mapping

from ageval.config.env_refs import keep_recovery_state_raw
from ageval.config.errors import ConfigError

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def resolve_keep_recovery_state(
    flag: bool | None,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """CLI flag wins. Unset falls back to ``AGEVAL_KEEP_RECOVERY_STATE``.

    Empty or absent env means delete the bundle after settlement. An explicit
    ``--no-keep-recovery-state`` overrides a true env value.
    """
    if flag is not None:
        return flag
    raw = keep_recovery_state_raw(env).strip().lower()
    if raw == "" or raw in _FALSE:
        return False
    if raw in _TRUE:
        return True
    raise ConfigError(
        "invalid_override",
        "AGEVAL_KEEP_RECOVERY_STATE must be a boolean (1/0, true/false, yes/no, on/off)",
        location="AGEVAL_KEEP_RECOVERY_STATE",
    )
