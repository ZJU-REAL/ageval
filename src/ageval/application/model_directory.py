"""Directory prices from the committed models.dev pin (Hub snapshot).

Used at suite-summary / upload time to persist observational cost.
Not a billed invoice, not PASS. Missing pin → no estimate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PIN_REL = Path("apps/hub/src/lib/model-pin/pin.json")


def _repo_root() -> Path:
    # src/ageval/application/model_directory.py → repo
    return Path(__file__).resolve().parents[3]


def load_model_pin() -> dict[str, Any] | None:
    path = _repo_root() / _PIN_REL
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("format") != "ageval.model-pin/1":
        return None
    return raw


def _peel_prefix(value: str, prefixes: list[str]) -> str | None:
    for prefix in prefixes:
        if not prefix:
            continue
        if prefix.endswith("-"):
            if value.startswith(prefix) and len(value) > len(prefix):
                return value[len(prefix) :]
            continue
        token = f"{prefix}/"
        if value.startswith(token):
            return value[len(token) :]
    return None


def _overlay_candidates(overlay: str, prefixes: list[str]) -> list[str]:
    text = overlay.strip()
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        next_ = value.strip().strip("/")
        if not next_ or next_ in seen:
            return
        seen.add(next_)
        out.append(next_)

    add(text)
    once = _peel_prefix(text, prefixes)
    if once:
        add(once)
        twice = _peel_prefix(once, prefixes)
        if twice:
            add(twice)
    parts = [p for p in text.split("/") if p]
    if parts:
        add(parts[-1])
    if len(parts) >= 2:
        add("/".join(parts[-2:]))
    return out


def join_overlay(overlay: str, pin: dict[str, Any] | None) -> str | None:
    text = overlay.strip()
    if not text or not pin:
        return None
    alias = str((pin.get("aliases") or {}).get(text) or "").strip()
    models = pin.get("models") or {}
    if alias and alias in models:
        return alias
    lookup = pin.get("lookup") or {}
    prefixes = list(pin.get("prefixes") or [])
    for candidate in _overlay_candidates(text, prefixes):
        unique: list[str] = []
        local: set[str] = set()
        for item in lookup.get(candidate) or []:
            if item in models and item not in local:
                local.add(item)
                unique.append(item)
        if len(unique) == 1:
            return unique[0]
    return None


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
