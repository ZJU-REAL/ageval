"""Profile id → a live Agent backend for this Attempt.

The task asks for a session by profile name and gets nothing else: the graph
that names the winning executor was fixed at lock time, and the box it attaches
to is the one this Attempt already opened. Nothing is re-resolved per invoke.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ageval.plugins.binding import bind_winner
from ageval.plugins.protocol import ExtensionGraph, intent_from_profile
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.resolve import resolve
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import ENVIRONMENT, EXECUTOR


class UnknownProfileError(LookupError):
    """The task asked for a profile the job never declared."""


@dataclass(frozen=True, slots=True)
class BoundAgent:
    """One executor instance plus the graph its chain slots come from."""

    profile_id: str
    plugin_id: str
    executor: Any
    graph: ExtensionGraph
    model: str


@dataclass
class AgentBinder:
    """Binds declared profiles to executors against one open box."""

    profiles: tuple[Mapping[str, Any], ...]
    services: ServiceTable
    registry: ExtensionRegistry
    environment: str | None = None
    environment_options: Mapping[str, Any] = field(default_factory=dict)
    requires: Mapping[str, Sequence[str]] = field(default_factory=dict)
    task_root: Path | None = None
    _graphs: dict[str, ExtensionGraph] = field(default_factory=dict, repr=False)

    def profile(self, profile_id: str) -> Mapping[str, Any]:
        for row in self.profiles:
            if str(row.get("id") or "") == profile_id:
                return row
        raise UnknownProfileError(profile_id)

    def graph(self, profile_id: str) -> ExtensionGraph:
        """Resolved graph for *profile_id* (one resolve per profile per Attempt).

        The empty id is the Attempt of a task that declares no role slot: it
        still needs a box, it just never opens a session.
        """
        found = self._graphs.get(profile_id)
        if found is not None:
            return found
        row = self.profile(profile_id) if profile_id else {}
        intent = intent_from_profile(
            row,
            environment=self.environment,
            environment_options=self.environment_options,
            requires=self.requires,
        )
        intent.profile_id = profile_id
        graph = resolve(intent, self.registry)
        self._graphs[profile_id] = graph
        return graph

    def bind(self, profile_id: str) -> BoundAgent:
        """Construct the executor for *profile_id* against the open box."""
        row = self.profile(profile_id)
        graph = self.graph(profile_id)
        winner = graph.winners[EXECUTOR]
        host = self.services.require(ENVIRONMENT)
        placement = host.placement()
        package_root = str(self.task_root) if self.task_root is not None else None
        from ageval.config.env_refs import resolve_locked_base_url

        raw_model = row.get("model")
        executor = bind_winner(
            self.registry,
            graph,
            EXECUTOR,
            profile_id=profile_id,
            model=executor_model_argument(raw_model),
            base_url=resolve_locked_base_url(_text(row.get("base_url"))),
            api_key=_text(row.get("api_key")),
            host=host,
            placement=placement,
            package_root=package_root,
        )
        return BoundAgent(
            profile_id=profile_id,
            plugin_id=winner.plugin_id,
            executor=executor,
            graph=graph,
            model=executor_model_id(raw_model),
        )


def executor_model_argument(raw: Any) -> str | dict[str, Any]:
    """Value passed to the executor factory. A missing model stays ``entry-default``."""
    from ageval.config.profiles import model_argument

    parsed = model_argument(raw)
    if parsed is None:
        return "entry-default"
    return parsed


def executor_model_id(raw: Any) -> str:
    """String id recorded on the session. Nested models use ``model.id``."""
    from ageval.config.profiles import model_id

    return model_id(raw) or "entry-default"


def _text(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None
