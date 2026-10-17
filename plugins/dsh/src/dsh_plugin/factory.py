"""dsh executor factory — bind the in-box worker to this Attempt's environment.

Parent never imports DeepSeekHarness. ``invoke`` builds a request and runs the
worker through ``host.exec``; credentials are locators projected into the exec
env at invoke time.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.model import ModelSpec, coerce_factory_model, require_model_support, spec_from_factory
from ageval.plugins.base import BaseExecutor
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.options import coerce_options, mapping_for_model
from dsh_plugin import PLUGIN_ID
from dsh_plugin.container import DshBoxExecutor
from dsh_plugin.options import (
    DEFAULT_COMPOSITION,
    DEFAULT_PROVIDER,
    SANDBOXED_COMPOSITION,
    DshOptions,
    parse_composition,
    parse_max_tokens,
    parse_permission,
)

DEFAULT_MODEL = "deepseek-v4-flash"
PERMISSION_ENV = "DSH_PERMISSION_MODE"
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


def _materialize(parse: Any, raw: Any) -> Any:
    try:
        return parse(raw)
    except ConfigError as exc:
        raise ExtensionMaterializeError(
            exc.message,
            kind="extension_materialize_failed",
        ) from exc


def _composition_slug(name: str | None) -> str:
    return _materialize(parse_composition, name)


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
    return _materialize(parse_max_tokens, raw)


def resolve_permission(raw: Any) -> str | None:
    """Validate ``options.permission``. Omit / blank → None (keep slim)."""
    return _materialize(parse_permission, raw)


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


@executor_plugin(priority=110, source="installed")
class DshExecutorSPI(BaseExecutor):
    """Executor SPI. The box runs the harness; this class owns the model contract."""

    kind = PLUGIN_ID
    requires_environment = True
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset(
        {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
    )
    extra_allowlist = frozenset()
    Options = DshOptions

    def __init__(
        self,
        *,
        options: dict[str, Any] | None = None,
        host: Any,
        placement: Any,
        profile_id: str | None = None,
        model: Any = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        raw = mapping_for_model(options)
        spec = spec_from_factory(coerce_factory_model(model), raw, default_id=DEFAULT_MODEL)
        self.supports_model(spec)
        self.bind_model(spec)
        parsed = options if isinstance(options, DshOptions) else coerce_options(DshOptions, raw)
        self.options = parsed
        permission = parsed.permission
        max_tokens = parsed.max_tokens
        composition = resolve_effective_composition(
            composition=parsed.composition,
            permission=permission,
        )
        resolve_composition_path(composition)
        provider = parsed.provider
        self._box = DshBoxExecutor(
            host=host,
            placement=placement,
            plugin_root=_plugin_root(),
            model=spec.id,
            provider=provider,
            composition=composition,
            permission=permission,
            max_tokens=max_tokens,
            base_url=base_url if isinstance(base_url, str) else None,
            api_key_env=api_key if isinstance(api_key, str) else None,
            session_id=f"ageval-{profile_id or 'solver'}-{uuid.uuid4().hex[:12]}",
        )
        self.model = self._box.model

    @classmethod
    def supports_model(cls, spec: ModelSpec) -> None:
        require_model_support(
            spec,
            supported_apis=cls.supported_apis,
            supported_model_fields=cls.supported_model_fields,
            extra_allowlist=cls.extra_allowlist,
        )

    def bind_model(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.reasoning_effort = spec.reasoning_effort

    @staticmethod
    def describe() -> dict[str, Any]:
        return describe_dsh()

    def open(self, **kwargs: Any) -> None:
        self._box.open(**kwargs)

    def close(self) -> None:
        self._box.close()

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> Any:
        del tools, messages
        return self._box.invoke(
            prompt,
            timeout=timeout,
            collect_dir=collect_dir,
            redaction_sentinels=redaction_sentinels,
        )


def build_executor(
    *,
    options: dict[str, Any] | None = None,
    host: Any,
    placement: Any,
    profile_id: str | None = None,
    model: Any = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> DshExecutorSPI:
    """Thin wrapper. plugin.yaml registers ``DshExecutorSPI``."""
    return DshExecutorSPI(
        options=options,
        host=host,
        placement=placement,
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )


__all__ = [
    "DEFAULT_COMPOSITION",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "DshExecutorSPI",
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
