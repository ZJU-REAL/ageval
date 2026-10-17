"""Example and suite profiles must set the highest effort tier.

When the model pin lists ``reasoning_options`` for a profile model, that
profile's ``reasoning.effort`` is the last tier or the ``max`` alias.
A model with no effort list is skipped.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ageval.model.pin import _effort_values, _model_row, load_model_pin

_REPO = Path(__file__).resolve().parents[1]


def _effort_of(model: Mapping[str, Any]) -> Any:
    reasoning = model.get("reasoning")
    if not isinstance(reasoning, Mapping):
        return None
    return reasoning.get("effort")


def _models_in(document: object) -> list[tuple[str, Mapping[str, Any]]]:
    if not isinstance(document, Mapping):
        return []
    found: list[tuple[str, Mapping[str, Any]]] = []

    def take(where: str, row: object) -> None:
        if not isinstance(row, Mapping):
            return
        model = row.get("model")
        if isinstance(model, Mapping) and isinstance(model.get("id"), str):
            found.append((where, model))

    binding = document.get("binding")
    if isinstance(binding, Mapping):
        take("binding", binding)
    profiles = document.get("agent_profiles")
    if isinstance(profiles, Mapping):
        for name, row in profiles.items():
            take(f"agent_profiles.{name}", row)
    elif isinstance(profiles, list):
        for index, row in enumerate(profiles):
            take(f"agent_profiles[{index}]", row)
    return found


def problems(root: Path, pin: Mapping[str, Any]) -> list[str]:
    """Profiles under *root* whose effort is below the pin's highest tier."""
    found: list[str] = []
    paths = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    for path in paths:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            found.append(f"{path}: {type(exc).__name__}")
            continue
        for where, model in _models_in(document):
            model_id = str(model["id"])
            row = _model_row(pin, model_id)
            if row is None:
                continue
            tiers = _effort_values(row)
            if not tiers:
                continue
            effort = _effort_of(model)
            if effort == "max" or effort == tiers[-1]:
                continue
            rel = path.relative_to(root) if path.is_relative_to(root) else path
            found.append(
                f"{rel}:{where} model {model_id} effort {effort!r} != {tiers[-1]!r} or max"
            )
    return found


def main() -> int:
    pin = load_model_pin()
    if not isinstance(pin, Mapping):
        print("model pin missing", file=sys.stderr)
        return 1
    found = problems(_REPO / "examples", pin)
    if found:
        print("\n".join(found), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
