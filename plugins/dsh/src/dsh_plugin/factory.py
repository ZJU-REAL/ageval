"""dsh executor factory — bind the in-box worker to this Attempt's environment.

Parent never imports DeepSeekHarness. ``invoke`` builds a request and runs the
worker through ``host.exec``; credentials are locators projected into the exec
env at invoke time.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from ageval.plugins.errors import ExtensionMaterializeError
from dsh_plugin import PLUGIN_ID
from dsh_plugin.container import DshBoxExecutor

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "deepseek-official"
DEFAULT_COMPOSITION = "slim"
SANDBOXED_COMPOSITION = "sandboxed"
PERMISSION_ENV = "DSH_PERMISSION_MODE"
PERMISSION_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})
_CREDENTIAL_ENV_NAMES = (
    "DEEPSEEK_API_KEY",
    "deepseek_api_key",
    "litellm_api_key",
)
_BASE_URL_ENV_FALLBACKS = (
    "DEEPSEEK_BASE_URL",
    "deepseek_base_url",
)
DEFAULT_BASE_URL = "https://api.deepseek.com"


def describe_dsh() -> dict[str, Any]:
    return {
        "execution_mode": "container-worker",
        "tools": "native",
        "structured_output": "validated-text",
        "session": "reuse-process",
        "stream": "native-events",
        "credential_env_names": _CREDENTIAL_ENV_NAMES,
        "binary": "dsh-jsonrpc-agent",
    }


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _composition_slug(name: str | None) -> str:
    slug = (name or DEFAULT_COMPOSITION).strip() or DEFAULT_COMPOSITION
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise ExtensionMaterializeError(
            f"dsh_composition_invalid:{slug}",
            kind="extension_materialize_failed",
        )
    return slug


def resolve_composition_path(name: str | None) -> Path:
    slug = _composition_slug(name)
    path = _plugin_root() / "compositions" / f"{slug}.cordis.yml"
    if not path.is_file():
        raise ExtensionMaterializeError(
            f"dsh_composition_missing:{slug}",
            kind="extension_materialize_failed",
        )
    return path


def resolve_max_tokens(raw: Any) -> int | None:
    """Validate ``options.max_tokens``. Omit / blank / null → no harness override."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ExtensionMaterializeError(
            f"dsh_max_tokens_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    return raw


def resolve_permission(raw: Any) -> str | None:
    """Validate ``options.permission``. Omit / blank → None (keep slim)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ExtensionMaterializeError(
            f"dsh_permission_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    value = raw.strip()
    if not value:
        return None
    if value not in PERMISSION_MODES:
        raise ExtensionMaterializeError(
            f"dsh_permission_invalid:{value}",
            kind="extension_materialize_failed",
        )
    return value


def resolve_effective_composition(*, composition: str | None, permission: str | None) -> str:
    explicit = (composition or "").strip()
    if permission and (not explicit or explicit == DEFAULT_COMPOSITION):
        return SANDBOXED_COMPOSITION
    return explicit or DEFAULT_COMPOSITION


def resolve_api_key_value(locator: str | None) -> str | None:
    names: list[str] = []
    if locator and str(locator).strip():
        names.append(str(locator).strip())
    for name in _CREDENTIAL_ENV_NAMES:
        if name not in names:
            names.append(name)
    for name in names:
        val = os.environ.get(name)
        if val and str(val).strip():
            return str(val).strip()
    return None


def resolve_base_url(explicit: str | None) -> str | None:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for key in _BASE_URL_ENV_FALLBACKS:
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()
    return DEFAULT_BASE_URL


def _model_id(model: Any) -> str:
    from ageval.config.profiles import model_id

    if model is None:
        return ""
    return model_id(model)


def build_executor(
    *,
    options: dict[str, Any] | None = None,
    host: Any,
    placement: Any,
    profile_id: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> DshBoxExecutor:
    """plugin.yaml exclusive entry: factory(**kwargs) → in-box executor."""
    opts = dict(options or {})
    permission = resolve_permission(opts.get("permission"))
    max_tokens = resolve_max_tokens(opts.get("max_tokens"))
    composition = resolve_effective_composition(
        composition=str(opts.get("composition") or "").strip() or None,
        permission=permission,
    )
    resolve_composition_path(composition)
    provider = str(opts.get("provider") or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER
    session_id = f"ageval-{profile_id or 'solver'}-{uuid.uuid4().hex[:12]}"
    return DshBoxExecutor(
        host=host,
        placement=placement,
        plugin_root=_plugin_root(),
        model=_model_id(model) or DEFAULT_MODEL,
        provider=provider,
        composition=composition,
        permission=permission,
        max_tokens=max_tokens,
        base_url=base_url if isinstance(base_url, str) else None,
        api_key_env=api_key if isinstance(api_key, str) else None,
        session_id=session_id,
    )


__all__ = [
    "DEFAULT_COMPOSITION",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "PERMISSION_ENV",
    "PLUGIN_ID",
    "build_executor",
    "describe_dsh",
    "resolve_api_key_value",
    "resolve_base_url",
    "resolve_effective_composition",
    "resolve_max_tokens",
    "resolve_permission",
]
