"""Test helpers: an AgentBinder bound to a scripted executor.

The executor is a stand-in for a real Agent backend so unit tests can exercise
the parent service's own rules (ceilings, deadlines, sealing). Nothing here is
evidence that an Agent path works — that is what the public smoke is for.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ageval.plugins.agent_result import AgentResult
from ageval.plugins.protocol import ExtensionGraph, WinnerRef
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import EXECUTOR
from ageval.runtime.agent_binding import AgentBinder, BoundAgent


class ScriptedExecutor:
    """Replies with the answer index of the call, or raises / stalls on demand."""

    kind = "scripted"

    def __init__(
        self,
        *,
        raises: BaseException | None = None,
        ok: bool = True,
        tool_calls: tuple[dict[str, Any], ...] | None = None,
        script: Sequence[AgentResult] | None = None,
    ) -> None:
        self.prompts: list[str] = []
        self.timeouts: list[float] = []
        self.tools: list[Any] = []
        self.messages: list[Any] = []
        self.closed = False
        self._raises = raises
        self._ok = ok
        self._tool_calls = tool_calls or ()
        self._script: list[AgentResult] | None = None if script is None else list(script)

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: Any = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
        tools: Any = None,
        messages: Any = None,
    ) -> AgentResult:
        del collect_dir, redaction_sentinels
        self.prompts.append(prompt)
        self.timeouts.append(timeout)
        self.tools.append(tools)
        self.messages.append(messages)
        if self._raises is not None:
            raise self._raises
        if self._script is not None:
            if not self._script:
                raise RuntimeError("scripted executor has no remaining result")
            return self._script.pop(0)
        turn = len(self.prompts)
        return AgentResult(
            model="scripted-model",
            text=f'{{"answer": {40 + turn}}}',
            structured={"answer": 40 + turn, "turn": turn},
            ok=self._ok,
            error=None if self._ok else "scripted_failure",
            metadata={"executor_kind": self.kind},
            tool_calls=self._tool_calls,
        )

    def close(self) -> None:
        self.closed = True


class ScriptedBinder(AgentBinder):
    """Binds one declared profile id to a fixed executor instance."""

    def __init__(
        self,
        executor: Any,
        *,
        profile_id: str = "solver",
        extra_profiles: tuple[str, ...] = (),
        options: dict[str, Any] | None = None,
    ) -> None:
        primary: dict[str, Any] = {"id": profile_id, "executor": ScriptedExecutor.kind}
        if options:
            primary["options"] = dict(options)
        rows = (primary,) + tuple(
            {"id": name, "executor": ScriptedExecutor.kind} for name in extra_profiles
        )
        super().__init__(
            profiles=rows,
            services=ServiceTable(),
            registry=ExtensionRegistry(),
        )
        self._executor = executor
        self.bind_calls = 0

    def bind(self, profile_id: str) -> BoundAgent:
        row = self.profile(profile_id)
        self.bind_calls += 1
        graph = ExtensionGraph(profile_id=profile_id)
        graph.winners[EXECUTOR] = WinnerRef(
            plugin_id=ScriptedExecutor.kind,
            impl=type(self._executor),
            priority=10,
            source="test",
            slot=EXECUTOR,
        )
        return BoundAgent(
            profile_id=profile_id,
            plugin_id=ScriptedExecutor.kind,
            executor=self._executor,
            graph=graph,
            model=str(row.get("model") or "scripted-model"),
        )
