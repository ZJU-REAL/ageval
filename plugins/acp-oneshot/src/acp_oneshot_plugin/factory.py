"""acp-oneshot ExecutorSPI — one host.exec per invoke, ACP stays in the box."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from acp_oneshot_plugin import PLUGIN_ID
from acp_oneshot_plugin.container import AcpOneshotBoxExecutor
from acp_oneshot_plugin.options import AcpOneshotOptions
from ageval.model import (
    ModelSpec,
    coerce_factory_model,
    require_model_support,
    spec_from_factory,
)
from ageval.plugins.base import BaseExecutor
from ageval.plugins.contrib.acp.entry_local import acp_stdio_argv
from ageval.plugins.contrib.acp.registry import AcpRegistryError, get_entry
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.options import coerce_options, mapping_for_model

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


@executor_plugin(priority=110, source="installed")
class AcpOneshotExecutorSPI(BaseExecutor):
    """Executor SPI. ACP stdio stays in the box; this class owns the model contract."""

    kind = PLUGIN_ID
    requires_environment = True
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset({"id", "api", "reasoning_effort", "extra"})
    extra_allowlist = frozenset()
    Options = AcpOneshotOptions

    def __init__(
        self,
        *,
        host: Any,
        placement: Any,
        options: dict[str, Any] | None = None,
        profile_id: str | None = None,
        model: Any = None,
        base_url: str | None = None,
        api_key: str | None = None,
        package_root: str | None = None,
    ) -> None:
        del package_root
        raw = mapping_for_model(options)
        spec = spec_from_factory(coerce_factory_model(model), raw, default_id="entry-default")
        self.supports_model(spec)
        self.bind_model(spec)
        parsed = (
            options
            if isinstance(options, AcpOneshotOptions)
            else coerce_options(AcpOneshotOptions, raw)
        )
        self.options = parsed
        entry = parsed.entry
        try:
            descriptor = get_entry(entry)
        except AcpRegistryError as exc:
            raise ExtensionMaterializeError(
                str(exc),
                kind="extension_materialize_failed",
            ) from exc
        if descriptor is None:
            raise ExtensionMaterializeError(
                f"unknown acp entry: {entry!r}",
                kind="extension_materialize_failed",
            )
        argv = acp_stdio_argv(
            entry,
            list(descriptor.acp_command),
            model=spec.id,
            reasoning_effort=spec.reasoning_effort,
        )
        self._box = AcpOneshotBoxExecutor(
            host=host,
            placement=placement,
            entry_id=entry,
            acp_command=argv,
            model=spec.id,
            reasoning_effort=spec.reasoning_effort,
            base_url=base_url if isinstance(base_url, str) else None,
            api_key_env=api_key if isinstance(api_key, str) else None,
            profile_id=profile_id,
            credential_env_names=descriptor.credential_env_names,
            fixed_env=dict(descriptor.fixed_env),
            descriptor=descriptor,
        )
        self.model = self._box.model
        self.acp_command = self._box.acp_command
        self.entry_id = self._box.entry_id

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
        return describe_acp_oneshot()

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
    host: Any,
    placement: Any,
    options: dict[str, Any] | None = None,
    profile_id: str | None = None,
    model: Any = None,
    base_url: str | None = None,
    api_key: str | None = None,
    package_root: str | None = None,
) -> AcpOneshotExecutorSPI:
    """Thin wrapper. plugin.yaml registers ``AcpOneshotExecutorSPI``."""
    return AcpOneshotExecutorSPI(
        host=host,
        placement=placement,
        options=options,
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        api_key=api_key,
        package_root=package_root,
    )


__all__ = ["AcpOneshotExecutorSPI", "build_executor", "describe_acp_oneshot"]
