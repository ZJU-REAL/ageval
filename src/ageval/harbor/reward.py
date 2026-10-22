"""Map a Harbor reward file onto an ageval PASS / FAIL verdict.

``reward.json`` wins over ``reward.txt``. The primary value is the ``reward``
key, or the only key when that name is absent. PASS is only ``1``, ``1.0``,
or ``true``. ``0`` and ``false`` are FAIL. A missing file is not a verdict.
"""

from __future__ import annotations

import json
import math
from typing import Any, NoReturn


def parse_reward_json(text: str) -> dict[str, Any]:
    """Parse a reward object. A bare number becomes ``{"reward": number}``."""
    if not text.strip():
        _fail("reward.json is empty")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"reward.json is not JSON: {exc}")
    if isinstance(parsed, dict):
        if not parsed:
            _fail("reward.json has no keys")
        for key, value in parsed.items():
            _require_score(value, f"reward.json key {key!r}")
        return parsed
    _require_score(parsed, "reward.json")
    return {"reward": parsed}


def parse_reward_text(text: str) -> dict[str, float]:
    """Parse the single number in ``reward.txt``."""
    if not text.strip():
        _fail("reward.txt is empty")
    try:
        value = float(text.strip())
    except ValueError:
        _fail("reward.txt is not a number")
    if not math.isfinite(value):
        _fail("reward.txt is not a finite number")
    return {"reward": value}


def verdict_from_rewards(rewards: dict[str, Any]) -> dict[str, Any]:
    """PASS iff the primary reward is 1, 1.0, or true. Other numbers are FAIL."""
    primary = _primary(rewards)
    _require_score(primary, "primary reward")
    passed = _is_pass(primary)
    metrics = {str(key): value for key, value in rewards.items() if key != "reward"}
    if isinstance(primary, bool):
        score = 1.0 if primary else 0.0
    elif isinstance(primary, int | float):
        score = float(primary)
    else:
        score = 0.0
    return {
        "status": "PASS" if passed else "FAIL",
        "score": score,
        "metrics": metrics,
    }


def _primary(rewards: dict[str, Any]) -> Any:
    if "reward" in rewards:
        return rewards["reward"]
    if len(rewards) == 1:
        return next(iter(rewards.values()))
    _fail("reward.json has multiple keys and no reward key")


def _is_pass(value: Any) -> bool:
    if isinstance(value, bool):
        return value is True
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return float(value) == 1.0
    return False


def _require_score(value: Any, where: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return
    _fail(f"{where} must be a boolean or a finite number")


def _fail(message: str) -> NoReturn:
    raise ValueError(message)
