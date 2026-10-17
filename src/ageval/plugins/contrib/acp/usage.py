"""ACP usage normalization (observational; not PASS authority)."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress as contextlib_suppress
from typing import Any

from ageval.evidence.usage import sealed_extra, sealed_usage


def _as_plain_mapping(obj: Any) -> dict[str, Any] | None:
    """Best-effort dict from pydantic model / mapping (snake_case preferred)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return dict(obj)
    with contextlib_suppress(TypeError, ValueError, AttributeError):
        if hasattr(obj, "model_dump"):
            # exclude_none + no alias → snake_case field names from acp.schema
            dumped = obj.model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dumped
    with contextlib_suppress(TypeError, ValueError, AttributeError):
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump(by_alias=True, exclude_none=True)
            if isinstance(dumped, dict):
                return dumped
    return None


def _pick_int(data: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key not in data:
            continue
        val = data[key]
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, float) and val == int(val):
            return int(val)
    return None


def _pick_number(data: Mapping[str, Any], *keys: str) -> float | int | None:
    for key in keys:
        if key not in data:
            continue
        val = data[key]
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            return val
    return None


def normalize_acp_usage(
    prompt_usage: Any = None,
    usage_update: Any = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Merge ACP dual-source usage into one observational dict (issue #30).

    Two protocol sources with different semantics:

    * ``PromptResponse.usage`` (``Usage``): billable/session **token** counts
      (``inputTokens`` / ``outputTokens`` / …).
    * ``sessionUpdate: usage_update`` (``UsageUpdate``): **context occupancy**
      (``used`` / ``size``) and optional session **cost** — ``used`` is *not*
      token total.

    Returns ``(usage, extra)``. Usage is first-class token/cost only; leftovers
    (context, sources, cache-write) are the sibling extra bag.

    ``cached_tokens`` is cached-read. Cache-write and the original cache-read
    count stay in ``extra`` (do not drop them). Missing fields stay absent.
    Never invents tokens from ``context.used``. Not PASS authority.
    """
    prompt_map = _as_plain_mapping(prompt_usage)
    update_map = _as_plain_mapping(usage_update)
    out: dict[str, Any] = {}
    has_prompt = False
    has_update = False

    if prompt_map:
        # Accept snake_case (model fields) and camelCase (wire / by_alias dump).
        token_pairs = (
            ("input_tokens", ("input_tokens", "inputTokens")),
            ("output_tokens", ("output_tokens", "outputTokens")),
            ("total_tokens", ("total_tokens", "totalTokens")),
            ("thought_tokens", ("thought_tokens", "thoughtTokens")),
            ("cached_read_tokens", ("cached_read_tokens", "cachedReadTokens")),
            ("cached_write_tokens", ("cached_write_tokens", "cachedWriteTokens")),
        )
        for out_key, aliases in token_pairs:
            val = _pick_int(prompt_map, *aliases)
            if val is not None:
                out[out_key] = val
                has_prompt = True
        # Derive total when both sides present and total missing.
        if "total_tokens" not in out:
            inp = out.get("input_tokens")
            outp = out.get("output_tokens")
            if isinstance(inp, int) and isinstance(outp, int):
                out["total_tokens"] = inp + outp
                has_prompt = True

    if update_map:
        # Context occupancy — never promote used → input_tokens.
        used = _pick_int(update_map, "used")
        size = _pick_int(update_map, "size")
        if used is not None or size is not None:
            ctx: dict[str, Any] = {}
            if used is not None:
                ctx["used"] = used
            if size is not None:
                ctx["size"] = size
            out["context"] = ctx
            has_update = True
        cost_raw = update_map.get("cost")
        cost_map = _as_plain_mapping(cost_raw) if cost_raw is not None else None
        if cost_map:
            amount = _pick_number(cost_map, "amount")
            currency = cost_map.get("currency")
            cost_out: dict[str, Any] = {}
            if amount is not None:
                cost_out["amount"] = amount
            if isinstance(currency, str) and currency.strip():
                cost_out["currency"] = currency.strip()
            if cost_out:
                out["cost"] = cost_out
                has_update = True
        elif used is not None or size is not None:
            pass  # context already recorded
        # Bare update with only sessionUpdate marker still counts as source if
        # we already got context/cost; else ignore empty shell.
        if not has_update and ("session_update" in update_map or "sessionUpdate" in update_map):
            # Keep raw empty update out of normalized payload.
            pass

    if not has_prompt and not has_update:
        return None, None

    extra: dict[str, Any] = {}
    if "total_tokens" in out:
        extra["total_tokens"] = out["total_tokens"]
    if "thought_tokens" in out:
        extra["thought_tokens"] = out["thought_tokens"]
    if "cached_read_tokens" in out:
        extra["cached_read_tokens"] = out["cached_read_tokens"]
    if "cached_write_tokens" in out:
        extra["cached_write_tokens"] = out["cached_write_tokens"]
    if "context" in out:
        extra["context"] = out["context"]
    extra["sources"] = {
        "prompt_usage": has_prompt,
        "usage_update": has_update,
    }

    cost_usd: float | int | None = None
    cost_map = out.get("cost")
    if isinstance(cost_map, dict):
        amount = cost_map.get("amount")
        currency = cost_map.get("currency")
        cur = currency.strip().upper() if isinstance(currency, str) else ""
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            if cur in {"", "USD"}:
                cost_usd = amount
            else:
                extra["cost"] = dict(cost_map)
        else:
            extra["cost"] = dict(cost_map)

    def _int_field(key: str) -> int | None:
        val = out.get(key)
        return val if isinstance(val, int) and not isinstance(val, bool) else None

    return (
        sealed_usage(
            prompt_tokens=_int_field("input_tokens"),
            completion_tokens=_int_field("output_tokens"),
            cached_tokens=_int_field("cached_read_tokens"),
            cost_usd=cost_usd,
        ),
        sealed_extra(extra or None),
    )
