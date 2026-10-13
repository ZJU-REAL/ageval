"""ACP session config options: model and reasoning-effort bind.

The parent is still the only JSON-RPC client. This module reads advertised
``configOptions`` (snake_case or camelCase) and calls ``set_config_option``.
It never opens a pipe and never learns a box handle.
"""

from __future__ import annotations

from typing import Any

# Advertised ACP config option ids that mean thinking / reasoning effort.
# Category ``thought_level`` is the protocol selector; these ids cover entries
# that omit the category or use a vendor-shaped id.
_REASONING_OPTION_IDS = frozenset(
    {"thought_level", "reasoning_effort", "reasoning", "thinking", "effort"}
)


def field(obj: Any, *names: str) -> Any:
    """Read a snake_case or camelCase attribute / mapping key."""
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict) and name in obj:
            val = obj[name]
            if val is not None:
                return val
        val = getattr(obj, name, None)
        if val is not None:
            return val
    return None


def config_options_from(obj: Any) -> Any:
    return field(obj, "config_options", "configOptions")


def select_option_values(opt: Any) -> list[str]:
    """Flatten a select option's values, including grouped choices."""
    raw = field(opt, "options")
    if not raw:
        return []
    values: list[str] = []
    for item in raw:
        grouped = field(item, "options")
        own = field(item, "value")
        if grouped and own is None:
            for child in grouped:
                val = field(child, "value")
                if val is not None:
                    values.append(str(val))
            continue
        if own is not None:
            values.append(str(own))
    return values


def find_reasoning_config_option(config_options: Any) -> Any:
    """First advertised thinking selector (category, then known ids)."""
    if not config_options:
        return None
    by_id = None
    for opt in config_options:
        if field(opt, "category") == "thought_level":
            return opt
        oid = field(opt, "id")
        if by_id is None and oid in _REASONING_OPTION_IDS:
            by_id = opt
    return by_id


async def bind_model(
    conn: Any,
    *,
    session_id: str | None,
    desired: str,
    model_binding: str,
    new_session_resp: Any,
) -> tuple[str, Any]:
    """Bind model. Returns ``(actual_model, latest configOptions)``."""
    initial = config_options_from(new_session_resp)
    if model_binding == "entry-default-only":
        if desired not in ("entry-default", "", None):
            raise RuntimeError("acp_model_unavailable")
        return "entry-default", initial

    if initial:
        for opt in initial:
            if field(opt, "category") != "model":
                continue
            config_id = field(opt, "id")
            current = field(opt, "current_value", "currentValue")
            values = select_option_values(opt)
            if desired == "entry-default":
                actual = str(current) if current is not None else "entry-default"
                return actual, initial
            if desired in values:
                resp = await conn.set_config_option(
                    config_id=str(config_id),
                    session_id=session_id,
                    value=desired,
                )
                return desired, config_options_from(resp) or initial
            raise RuntimeError("acp_model_unavailable")

    models = getattr(new_session_resp, "models", None)
    if models is not None:
        available = getattr(models, "available_models", None) or getattr(
            models, "availableModels", None
        )
        if available and desired != "entry-default":
            ids: list[str] = []
            for item in available:
                mid = getattr(item, "model_id", None) or getattr(item, "modelId", None)
                if mid:
                    ids.append(str(mid))
            if desired not in ids:
                raise RuntimeError("acp_model_unavailable")
        actual = desired if desired != "entry-default" else "entry-default"
        return actual, initial

    # No model surface — entry default only. Do not treat the profile
    # string as a silent hint.
    if desired not in ("entry-default", "", None):
        raise RuntimeError("acp_model_unavailable")
    return "entry-default", initial


async def bind_reasoning_effort(
    conn: Any,
    *,
    session_id: str | None,
    desired: str | None,
    config_options: Any,
) -> str | None:
    """Apply ``model.reasoning.effort`` to the advertised selector."""
    if not desired:
        return None
    opt = find_reasoning_config_option(config_options)
    if opt is None:
        raise RuntimeError("acp_reasoning_effort_unavailable")
    config_id = field(opt, "id")
    current = field(opt, "current_value", "currentValue")
    values = select_option_values(opt)
    if current is not None and desired == str(current):
        return desired
    if not config_id or desired not in values:
        raise RuntimeError("acp_reasoning_effort_unavailable")
    await conn.set_config_option(
        config_id=str(config_id),
        session_id=session_id,
        value=desired,
    )
    return desired
