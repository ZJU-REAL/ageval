"""Resolve ``reasoning.effort: max`` from the committed model pin.

``max`` is an alias for the last ``reasoning_options`` effort tier. A pin
row with no effort list fails the lock. The lock stores the tier, so a
later run does not have to guess. When the highest tier is itself the
string ``max``, that string is the tier.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ageval.model.errors import ModelConfigError

_PIN_REL = Path("apps/shared/lib/model-pin/pin.json")
_ALIAS = "max"


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
    parts = [part for part in text.split("/") if part]
    if parts:
        add(parts[-1])
    if len(parts) >= 2:
        add("/".join(parts[-2:]))
    return out


def join_overlay(overlay: str, pin: Mapping[str, Any] | None) -> str | None:
    """Canonical pin model id for a gateway-prefixed overlay, when it is unique."""
    text = overlay.strip()
    if not text or not isinstance(pin, Mapping):
        return None
    aliases = pin.get("aliases") or {}
    models = pin.get("models") or {}
    if not isinstance(aliases, Mapping):
        aliases = {}
    if not isinstance(models, Mapping):
        return None
    alias = str(aliases.get(text) or "").strip()
    if alias and alias in models:
        return alias
    lookup = pin.get("lookup") or {}
    if not isinstance(lookup, Mapping):
        lookup = {}
    raw_prefixes = pin.get("prefixes") or []
    prefixes = list(raw_prefixes) if isinstance(raw_prefixes, list) else []
    for candidate in _overlay_candidates(text, prefixes):
        unique: list[str] = []
        local: set[str] = set()
        rows = lookup.get(candidate) or []
        if not isinstance(rows, list):
            continue
        for item in rows:
            if item in models and item not in local:
                local.add(item)
                unique.append(item)
        if len(unique) == 1:
            return unique[0]
    return None


def _repo_root() -> Path:
    # src/ageval/model/pin.py → repo
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


def _model_row(pin: Mapping[str, Any], model_id: str) -> Mapping[str, Any] | None:
    models = pin.get("models")
    if not isinstance(models, Mapping):
        return None
    direct = models.get(model_id)
    if isinstance(direct, Mapping):
        return direct
    aliases = pin.get("aliases")
    if isinstance(aliases, Mapping):
        target = aliases.get(model_id)
        if isinstance(target, str):
            aliased = models.get(target)
            if isinstance(aliased, Mapping):
                return aliased
    canonical = join_overlay(model_id, pin)
    if isinstance(canonical, str):
        joined = models.get(canonical)
        if isinstance(joined, Mapping):
            return joined
    return None


def _effort_values(row: Mapping[str, Any]) -> list[str]:
    options = row.get("reasoning_options")
    if not isinstance(options, list):
        return []
    found: list[str] = []
    for item in options:
        if not isinstance(item, Mapping) or item.get("type") != "effort":
            continue
        values = item.get("values")
        if not isinstance(values, list):
            continue
        tiers = [value.strip() for value in values if isinstance(value, str) and value.strip()]
        if tiers:
            found = tiers
    return found


def resolve_effort_max(
    model_id: str,
    *,
    pin: Mapping[str, Any] | None = None,
    strict: bool = True,
) -> str:
    """Return the highest effort tier for ``model_id``.

    ``strict`` fails when the pin file is absent (lock). A runtime resolve
    with no pin file keeps the string ``max``, which is also a real tier
    name on some rows. A pin that is present and has no effort list fails
    either way.
    """
    loaded = pin if pin is not None else load_model_pin()
    if not isinstance(loaded, Mapping):
        if strict:
            raise ModelConfigError(
                f"reasoning.effort max for {model_id!r} needs the model pin; set a concrete tier"
            )
        return _ALIAS
    row = _model_row(loaded, model_id)
    if row is None:
        raise ModelConfigError(
            f"reasoning.effort max for {model_id!r} is not in the model pin; set a concrete tier"
        )
    tiers = _effort_values(row)
    if not tiers:
        raise ModelConfigError(
            f"reasoning.effort max for {model_id!r} has no pin reasoning_options "
            "effort list; set a concrete tier"
        )
    return tiers[-1]


def rewrite_profile_effort_max(
    profile: dict[str, Any],
    *,
    pin: Mapping[str, Any] | None = None,
) -> None:
    """Replace a profile's ``reasoning.effort: max`` with the pin tier."""
    model = profile.get("model")
    if not isinstance(model, dict):
        return
    reasoning = model.get("reasoning")
    if not isinstance(reasoning, dict):
        return
    effort = reasoning.get("effort")
    if not isinstance(effort, str) or effort.strip() != _ALIAS:
        return
    raw_id = model.get("id")
    model_id = raw_id.strip() if isinstance(raw_id, str) else ""
    reasoning["effort"] = resolve_effort_max(model_id or str(raw_id), pin=pin, strict=True)
