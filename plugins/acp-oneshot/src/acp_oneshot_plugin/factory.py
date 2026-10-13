"""acp-oneshot ExecutorSPI — one host.exec per invoke, ACP stays in the box."""

from __future__ import annotations

from typing import Any

from acp_oneshot_plugin.container import AcpOneshotBoxExecutor
from ageval.plugins.contrib.acp.entry_local import acp_stdio_argv
from ageval.plugins.contrib.acp.registry import get_entry
from ageval.plugins.errors import ExtensionMaterializeError

_EXECUTION_MODE = "acp-oneshot"


def describe_acp_oneshot(*, entry_id: str | None = None) -> dict[str, Any]:
    """Inventory surface. execution_mode is this wrap, not acp-stdio."""
    credential_env_names: tuple[str, ...] = ()
    binary = ""
    if entry_id:
        descriptor = get_entry(entry_id)
        if descriptor is not None:
            credential_env_names = descriptor.credential_env_names
            binary = descriptor.acp_command[0] if descriptor.acp_command else ""
    return {
        "execution_mode": _EXECUTION_MODE,
        "tools": "native",
        "structured_output": "validated-text",
        "session": "one-shot",
        "stream": "none",
        "credential_env_names": credential_env_names,
        "binary": binary,
    }


def _model_id(model: Any) -> str:
    from ageval.config.profiles import model_id

    if model is None:
        return ""
    return model_id(model)


def build_executor(
    *,
    host: Any,
    placement: Any,
    options: dict[str, Any] | None = None,
    profile_id: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    package_root: str | None = None,
) -> AcpOneshotBoxExecutor:
    """plugin.yaml exclusive entry: factory receives host + placement from bind_winner."""
    del package_root
    opts = dict(options or {})
    entry = str(opts.get("entry") or "").strip()
    if not entry:
        raise ExtensionMaterializeError(
            "acp_entry_required",
            kind="extension_materialize_failed",
        )
    descriptor = get_entry(entry)
    if descriptor is None:
        raise ExtensionMaterializeError(
            f"unknown acp entry: {entry!r}",
            kind="extension_materialize_failed",
        )
    model_s = _model_id(model) or "entry-default"
    effort = opts.get("reasoning_effort")
    effort_s = str(effort).strip() if isinstance(effort, str) and effort.strip() else None
    argv = acp_stdio_argv(
        entry,
        list(descriptor.acp_command),
        model=model_s,
        reasoning_effort=effort_s,
    )
    return AcpOneshotBoxExecutor(
        host=host,
        placement=placement,
        entry_id=entry,
        acp_command=argv,
        model=model_s,
        reasoning_effort=effort_s,
        base_url=base_url if isinstance(base_url, str) else None,
        api_key_env=api_key if isinstance(api_key, str) else None,
        profile_id=profile_id,
        credential_env_names=descriptor.credential_env_names,
        fixed_env=dict(descriptor.fixed_env),
        descriptor=descriptor,
    )


__all__ = ["build_executor", "describe_acp_oneshot"]
