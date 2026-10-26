"""BaseEnvironment / BaseExecutor: abstracts are required, model methods too."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from ageval.environments.protocol import (
    EnvironmentCapabilities,
    EnvironmentProvider,
    ExecResult,
    Placement,
    StdioTransport,
)
from ageval.model import ModelConfigError, ModelSpec, require_model_support, resolve_model
from ageval.plugins.base import BaseEnvironment, BaseExecutor
from ageval.plugins.protocol import ExecutorSPI


class _ReadyEnvironment(BaseEnvironment):
    kind = "local"
    capabilities = EnvironmentCapabilities(
        exec=True,
        upload=True,
        download=True,
        attach_stdio=True,
    )
    python_command = ("python3",)

    async def preflight(self) -> None:
        return None

    async def start(self, *, force_build: bool = False) -> None:
        del force_build
        return None

    async def stop(self, *, delete: bool) -> None:
        del delete
        return None

    def placement(self) -> Placement:
        return Placement(target_id="local:ready")

    def visible_path(self, box_path: str) -> str:
        return box_path

    async def exec(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        user: str | None = None,
        service: str | None = None,
    ) -> ExecResult:
        del command, cwd, env, timeout_sec, user, service
        return ExecResult(0)

    async def upload(self, source: object, dest: str, *, service: str | None = None) -> None:
        del source, dest, service

    async def download(self, source: str, dest: object, *, service: str | None = None) -> None:
        del source, dest, service

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> StdioTransport:
        del argv, placement, env, request_id
        raise AssertionError("not used")


class _HttpExecutor(BaseExecutor):
    kind = "openai-http"
    requires_environment = False
    supported_apis = frozenset({"chat"})
    supported_model_fields = frozenset(
        {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
    )
    extra_allowlist: frozenset[str] = frozenset()
    bound: ModelSpec | None = None

    @classmethod
    def supports_model(cls, spec: ModelSpec) -> None:
        require_model_support(
            spec,
            supported_apis=cls.supported_apis,
            supported_model_fields=cls.supported_model_fields,
            extra_allowlist=cls.extra_allowlist,
        )

    def bind_model(self, spec: ModelSpec) -> None:
        self.supports_model(spec)
        self.bound = spec

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> str:
        del timeout, collect_dir, redaction_sentinels, tools, messages
        return prompt

    def close(self) -> None:
        return None


def test_incomplete_environment_and_executor_cannot_be_instantiated() -> None:
    class _BareEnvironment(BaseEnvironment):
        kind = "local"
        capabilities = EnvironmentCapabilities()
        python_command = ("python3",)

    class _BareExecutor(BaseExecutor):
        kind = "openai-http"
        supported_apis = frozenset({"chat"})
        supported_model_fields = frozenset({"id", "api"})
        extra_allowlist = frozenset()

    with pytest.raises(TypeError):
        _BareEnvironment()  # pyright: ignore[reportAbstractUsage]
    with pytest.raises(TypeError):
        _BareExecutor()  # pyright: ignore[reportAbstractUsage]


def test_missing_model_methods_cannot_be_instantiated() -> None:
    class _NoModel(BaseExecutor):
        kind = "openai-http"
        requires_environment = False
        supported_apis = frozenset({"chat"})
        supported_model_fields = frozenset({"id", "api"})
        extra_allowlist = frozenset()

        def invoke(self, prompt: str, **kwargs: Any) -> str:
            del kwargs
            return prompt

        def close(self) -> None:
            return None

    with pytest.raises(TypeError):
        _NoModel()  # pyright: ignore[reportAbstractUsage]
    assert "consumes_model" not in BaseExecutor.__dict__
    assert "extra_allowlist" not in BaseExecutor.__dict__
    assert "exec" not in BaseEnvironment.__dict__
    assert "upload" not in BaseEnvironment.__dict__
    assert "download" not in BaseEnvironment.__dict__
    assert "attach_stdio" not in BaseEnvironment.__dict__


def test_ready_classes_match_the_existing_protocols() -> None:
    host = _ReadyEnvironment()
    assert host.kind == "local"
    assert isinstance(host.capabilities, EnvironmentCapabilities)
    assert isinstance(host, EnvironmentProvider)
    executor = _HttpExecutor()
    assert executor.requires_environment is False
    assert executor.open() is None
    assert executor.open(session="s") is None
    assert isinstance(executor, ExecutorSPI)
    spec = resolve_model({"id": "openai/example-model", "reasoning": {"effort": "xhigh"}})
    executor.bind_model(spec)
    assert executor.bound == spec
    assert executor.invoke("hello") == "hello"
    with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
        executor.supports_model(resolve_model({"id": "m", "extra": {"temperature": 1}}))
