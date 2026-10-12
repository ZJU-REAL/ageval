"""ACP first-party contrib: parent client, entry registry, executor SPI.

Not an external ``plugins/acp`` package and not installed via ``ageval plugin
install``. Official Attempt images bake every shipped entry; task recipes
also stack ``config.image_layers`` for the bound ``options.entry``.
"""

from __future__ import annotations

from typing import Any

from ageval.plugins.contrib.acp.executor import AcpExecutor
from ageval.plugins.contrib.acp.hooks import ENSURE_RUNTIME_PRIORITY, ensure_runtime
from ageval.plugins.contrib.acp.trajectory_map import acp_session_events_to_ageval
from ageval.plugins.contrib.acp.usage import normalize_acp_usage
from ageval.plugins.protocol import InjectRequirement
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.slots import (
    AFTER_ENVIRONMENT_READY,
    ENVIRONMENT,
    EXECUTOR,
    TRAJECTORY_COLLECT,
)

PLUGIN_ID = "acp"
# Stronger than default multi (1000); weaker than explicit profile binding.
ACP_PRIORITY = 100


def build_acp_executor(**kwargs: Any) -> AcpExecutor:
    """Bind the ``executor`` slot: one ACP entry attached to this Attempt's box."""
    return AcpExecutor(**kwargs)


async def _acp_trajectory_collect(ctx: Any, value: Any, nxt: Any) -> Any:
    """Tag trajectory payload as ACP-sourced; seal path writes from chain output (#71 B)."""
    out = await nxt(value)
    if isinstance(out, dict):
        meta = dict(out.get("metadata") or {})
        meta.setdefault("trajectory_source", "acp")
        return {**out, "metadata": meta}
    return out


def register_acp_contrib(registry: ExtensionRegistry) -> None:
    registry.exclusive(
        EXECUTOR,
        PLUGIN_ID,
        AcpExecutor,
        priority=ACP_PRIORITY,
        source="first-party",
        is_factory=True,
    )
    registry.chain(
        AFTER_ENVIRONMENT_READY,
        PLUGIN_ID,
        ensure_runtime,
        priority=ENSURE_RUNTIME_PRIORITY,
        source="first-party",
        is_factory=True,
    )
    registry.chain(
        TRAJECTORY_COLLECT,
        PLUGIN_ID,
        _acp_trajectory_collect,
        priority=ACP_PRIORITY,
        source="first-party",
    )
    # The pipe always comes from the box, so the box must be able to attach one.
    registry.declare_inject(
        PLUGIN_ID,
        (InjectRequirement(service=ENVIRONMENT, capabilities=("attach_stdio",)),),
    )


__all__ = [
    "PLUGIN_ID",
    "AcpExecutor",
    "acp_session_events_to_ageval",
    "build_acp_executor",
    "ensure_runtime",
    "normalize_acp_usage",
    "register_acp_contrib",
]
