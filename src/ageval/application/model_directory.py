"""Directory prices from the committed models.dev pin (Hub snapshot).

Used at suite-summary / upload time to persist observational cost.
Not a billed invoice, not PASS. Missing pin → no estimate.
"""

from __future__ import annotations

from typing import Any

from ageval.model.pin import _peel_prefix, join_overlay

__all__ = [
    "directory_price",
    "estimate_cost_usd",
    "join_overlay",
    "load_model_pin",
]


def load_model_pin() -> dict[str, Any] | None:
    from ageval.model.pin import load_model_pin as _load

    return _load()


def directory_price(
    overlay: str,
    pin: dict[str, Any] | None,
) -> dict[str, float] | None:
    """USD per million tokens for this overlay, from the pin snapshot."""
    text = overlay.strip()
    if not text or pin is None:
        return None
    canonical = join_overlay(text, pin)
    raw_prices = pin.get("prices")
    prices = raw_prices if isinstance(raw_prices, dict) else {}
    row = prices.get(canonical) if canonical else None
    if not isinstance(row, dict) or not row:
        return None
    prefixes = list(pin.get("prefixes") or [])
    peeled = _peel_prefix(text, prefixes)
    provider_from_overlay = text.split("/", 1)[0] if "/" in text else ""
    for key in (provider_from_overlay, (peeled.split("/", 1)[0] if peeled else "")):
        hit = row.get(key) if key else None
        if isinstance(hit, dict) and isinstance(hit.get("input"), (int, float)):
            out = hit.get("output")
            return {
                "input": float(hit["input"]),
                "output": float(out) if isinstance(out, (int, float)) else 0.0,
            }
    raw_models = pin.get("models")
    models = raw_models if isinstance(raw_models, dict) else {}
    lab = (models.get(canonical) or {}).get("lab") if canonical else None
    if isinstance(lab, str) and isinstance(row.get(lab), dict):
        hit = row[lab]
        if isinstance(hit.get("input"), (int, float)):
            out = hit.get("output")
            return {
                "input": float(hit["input"]),
                "output": float(out) if isinstance(out, (int, float)) else 0.0,
            }
    first = next(iter(row.values()), None)
    if isinstance(first, dict) and isinstance(first.get("input"), (int, float)):
        out = first.get("output")
        return {
            "input": float(first["input"]),
            "output": float(out) if isinstance(out, (int, float)) else 0.0,
        }
    return None


def estimate_cost_usd(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cached_tokens: int | None,
    overlay: str,
    pin: dict[str, Any] | None,
) -> float | None:
    if prompt_tokens is None and completion_tokens is None:
        return None
    price = directory_price(overlay, pin)
    if price is None:
        return None
    cached = cached_tokens or 0
    billed_prompt = max(0, (prompt_tokens or 0) - cached)
    return (
        (billed_prompt / 1_000_000) * price["input"]
        + (cached / 1_000_000) * price["input"]
        + ((completion_tokens or 0) / 1_000_000) * price["output"]
    )
