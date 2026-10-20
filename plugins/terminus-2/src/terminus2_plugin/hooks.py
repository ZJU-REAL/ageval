"""trajectory_collect for terminus-2 events already on the ageval schema."""

from __future__ import annotations

from typing import Any

from terminus2_plugin import PLUGIN_ID
from terminus2_plugin.trajectory import SCHEMA


async def trajectory_collect(ctx: Any, value: Any, nxt: Any) -> Any:
    del ctx
    out = await nxt(value)
    if not isinstance(out, dict):
        return out
    events = out.get("events")
    if not isinstance(events, list | tuple) or not events:
        return out
    if not any(isinstance(event, dict) and event.get("source") == PLUGIN_ID for event in events):
        return out
    if not all(isinstance(event, dict) and event.get("schema") == SCHEMA for event in events):
        return out
    meta = dict(out.get("metadata") or {})
    meta.setdefault("trajectory_source", PLUGIN_ID)
    return {**out, "metadata": meta}


__all__ = ["trajectory_collect"]
