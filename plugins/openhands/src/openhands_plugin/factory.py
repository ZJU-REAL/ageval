"""OpenHands executor factory.

The parent never imports the OpenHands SDK. ``invoke`` uploads a worker and
runs it through ``host.exec``. Credentials are locators projected into that
process. The SDK itself stays inside the Attempt environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.model import ModelSpec, coerce_factory_model, require_model_support, spec_from_factory
from ageval.plugins.base import BaseExecutor
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.options import coerce_options, mapping_for_model
from openhands_plugin import PLUGIN_ID
from openhands_plugin.container import OpenHandsBoxExecutor
from openhands_plugin.options import OpenHandsOptions

_DEFAULT_MODEL_ID = "openai/gpt-4.1-mini"

_BASE_URL_ENV_FALLBACKS = (
    "OPENAI_BASE_URL",
    "litellm_base_url",
    "AGEVAL_OPENAI_BASE_URL",
)


def describe_openhands() -> dict[str, Any]:
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


@executor_plugin(priority=110, source="installed")
class OpenHandsExecutorSPI(BaseExecutor):
    """Executor SPI. The environment runs the SDK; this class owns the model contract."""

    kind = PLUGIN_ID
    requires_environment = True
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset(
        {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
    )
    extra_allowlist = frozenset()
    Options = OpenHandsOptions

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
        package_root: str | None = None,
    ) -> None:
        del profile_id, package_root
        raw = mapping_for_model(options)
        spec = spec_from_factory(coerce_factory_model(model), raw, default_id=_DEFAULT_MODEL_ID)
        self.supports_model(spec)
        self.bind_model(spec)
        if isinstance(options, OpenHandsOptions):
            parsed = options
        else:
            parsed = coerce_options(OpenHandsOptions, raw)
        self.options = parsed
        self._box = OpenHandsBoxExecutor(
            host=host,
            placement=placement,
            plugin_root=_plugin_root(),
            version=parsed.version,
            max_iterations=parsed.max_iterations,
            model=spec.id,
            api=spec.api,
            reasoning_effort=spec.reasoning_effort,
            timeout=spec.timeout,
            base_url=base_url if isinstance(base_url, str) else None,
            api_key_env=api_key if isinstance(api_key, str) else None,
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
        return describe_openhands()

    def bind_activity(self, scope: Any) -> None:
        super().bind_activity(scope)
        self._box.activity = scope

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
    package_root: str | None = None,
) -> OpenHandsExecutorSPI:
    """Thin wrapper. plugin.yaml registers ``OpenHandsExecutorSPI``."""
    return OpenHandsExecutorSPI(
        options=options,
        host=host,
        placement=placement,
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        api_key=api_key,
        package_root=package_root,
    )


__all__ = [
    "PLUGIN_ID",
    "OpenHandsExecutorSPI",
    "build_executor",
    "describe_openhands",
    "resolve_api_key_value",
    "resolve_base_url",
]
