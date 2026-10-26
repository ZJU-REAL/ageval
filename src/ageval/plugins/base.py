"""Shared bases for environment and executor plugins.

Registration checks live in ``ageval.plugins.decorators``. This module does
not register anything. Lock calls ``supports_model`` for a class winner
and checks ``requires_environment`` against the injected environment caps.
``exec`` / ``upload`` / ``download`` / ``attach_stdio`` are absent on
``BaseEnvironment`` so a registration check can see that the subclass did
not implement them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from ageval.environments.protocol import (
    EnvironmentCapabilities,
    EnvironmentFailure,
    Placement,
    ProbeStatus,
)
from ageval.model.spec import ModelSpec


class BaseEnvironment(ABC):
    """Exclusive ``environment`` winner. Subclasses match ``EnvironmentProvider``.

    ``capabilities`` is ``EnvironmentCapabilities`` from the environment
    protocol. Always-on methods are abstract. A capability that is true still
    needs its method on the subclass; this class does not supply one.
    """

    kind: str
    capabilities: EnvironmentCapabilities
    python_command: tuple[str, ...]

    @abstractmethod
    async def preflight(self) -> None:
        """Fail at lock time when this environment cannot be opened here."""

    @abstractmethod
    async def start(self, *, force_build: bool = False) -> None:
        """Open the environment for one Attempt."""

    def runtime_handle(self) -> dict[str, Any]:
        """JSON handle for a started box. Kinds that can reattach override this."""
        return {}

    async def probe(self, handle: Mapping[str, Any]) -> ProbeStatus:
        """Default: the previous box is not reusable until the kind implements probe."""
        del handle
        return ProbeStatus(status="absent")

    async def attach(self, handle: Mapping[str, Any]) -> None:
        """Default: refuse. ``local`` and ``docker`` bind a live box instead."""
        del handle
        msg = "this environment cannot attach to an existing box"
        raise EnvironmentFailure("environment_attach_invalid", msg)

    async def discard(self, handle: Mapping[str, Any]) -> None:
        """Stop a previously recorded box. The default leaves the directory in place."""
        del handle

    @abstractmethod
    async def stop(self, *, delete: bool) -> None:
        """Release the environment. ``delete`` drops its work root when true."""

    @abstractmethod
    def placement(self) -> Placement:
        """Engine-issued attach facts. No vendor handle."""

    @abstractmethod
    def visible_path(self, box_path: str) -> str:
        """In-environment path as a process inside it sees that path."""


class BaseExecutor(ABC):
    """Exclusive ``executor`` winner. Every executor binds a ``ModelSpec``.

    ``extra_allowlist``, ``supported_apis``, and ``supported_model_fields``
    have no default. An empty ``extra_allowlist`` rejects every extra key.
    ``supports_model`` raises ``ModelConfigError``; that is a config error.
    """

    kind: str
    requires_environment: bool = True
    supported_apis: frozenset[str]
    supported_model_fields: frozenset[str]
    extra_allowlist: frozenset[str]

    @classmethod
    @abstractmethod
    def supports_model(cls, spec: ModelSpec) -> None:
        """Raise ``ModelConfigError`` when this executor cannot accept ``spec``.

        Lock calls this on the class and does not construct an instance.
        """

    @abstractmethod
    def bind_model(self, spec: ModelSpec) -> None:
        """Store a validated spec. ``extra`` may contain only allowlisted keys."""

    @abstractmethod
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
        """One session turn."""

    @abstractmethod
    def close(self) -> None:
        """Release process and session resources."""

    def open(self, **kwargs: Any) -> None:
        """Optional session open. The default does nothing."""
        del kwargs
        return None

    def bind_activity(self, scope: Any) -> None:
        """Remember the parent activity scope for this executor. Default stores it."""
        self.activity = scope
