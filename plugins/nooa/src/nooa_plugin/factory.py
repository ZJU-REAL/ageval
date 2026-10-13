"""nooa executor factory — bind the in-box worker to this Attempt's environment.

Parent never imports NVIDIA nooa or LiteLLM as the success path. ``invoke``
builds a request and runs the worker through ``host.exec``; credentials are
locators projected into the exec env at invoke time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ageval.plugins.errors import ExtensionMaterializeError
from nooa_plugin import PLUGIN_ID
from nooa_plugin.container import NooaBoxExecutor

_BASE_URL_ENV_FALLBACKS = (
    "OPENAI_BASE_URL",
    "litellm_base_url",
    "AGEVAL_OPENAI_BASE_URL",
)


def describe_nooa() -> dict[str, Any]:
    return {
        "execution_mode": "container-worker",
        "tools": "native",
        "structured_output": "validated-text",
        "session": "unsupported",
        "stream": "synthetic-lifecycle",
        "credential_env_names": ("OPENAI_API_KEY", "litellm_api_key"),
        "binary": "",
    }


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_api_key_value(locator: str | None) -> str | None:
    if not locator or not str(locator).strip():
        names = ["OPENAI_API_KEY", "litellm_api_key"]
    else:
        name = str(locator).strip()
        names = [name]
        if name != "OPENAI_API_KEY":
            names.append("OPENAI_API_KEY")
    for name in names:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    return None


def resolve_base_url(explicit: str | None) -> str | None:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for key in _BASE_URL_ENV_FALLBACKS:
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()
    return None


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
    package_root: str | None = None,
) -> NooaBoxExecutor:
    """plugin.yaml exclusive entry: factory(**kwargs) → in-box executor."""
    del profile_id
    opts = dict(options or {})
    agent_ref = opts.get("agent")
    if not agent_ref or not str(agent_ref).strip():
        raise ExtensionMaterializeError(
            "nooa_options_agent_required",
            kind="extension_materialize_failed",
        )
    return NooaBoxExecutor(
        host=host,
        placement=placement,
        plugin_root=_plugin_root(),
        package_root=package_root,
        agent_ref=str(agent_ref).strip(),
        method=str(opts.get("method") or "run").strip() or "run",
        model=_model_id(model) or "openai/gpt-4.1-mini",
        base_url=base_url if isinstance(base_url, str) else None,
        api_key_env=api_key if isinstance(api_key, str) else None,
    )


__all__ = [
    "PLUGIN_ID",
    "build_executor",
    "describe_nooa",
    "resolve_api_key_value",
    "resolve_base_url",
]
