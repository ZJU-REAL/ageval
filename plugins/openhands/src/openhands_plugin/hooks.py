"""trajectory_collect handler for the OpenHands executor."""

from __future__ import annotations

from typing import Any

from openhands_plugin import PLUGIN_ID


async def trajectory_collect(ctx: Any, value: Any, nxt: Any) -> Any:
    """Map this plugin's native steps. Leave another plugin's events alone."""
    del ctx
    out = await nxt(value)
    if not isinstance(out, dict):
        return out
    from openhands_plugin.trajectory import SCHEMA, to_ageval_trajectory_events

    events = out.get("events")
    if not isinstance(events, (list, tuple)) or not events:
        return out
    if all(isinstance(row, dict) and row.get("schema") == SCHEMA for row in events):
        if not any(row.get("source") == PLUGIN_ID for row in events if isinstance(row, dict)):
            return out
        meta = dict(out.get("metadata") or {})
        meta.setdefault("trajectory_source", PLUGIN_ID)
        return {**out, "metadata": meta}
    native = tuple(row for row in events if isinstance(row, dict) and row.get("type"))
    if not native:
        return out
    mapped = to_ageval_trajectory_events(native)
    meta = dict(out.get("metadata") or {})
    meta.setdefault("trajectory_source", PLUGIN_ID)
    return {**out, "events": tuple(mapped), "metadata": meta}


__all__ = ["trajectory_collect"]
