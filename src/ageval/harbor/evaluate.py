"""Built-in Harbor score: run ``tests/test.sh`` and read the reward file."""

from __future__ import annotations

import shlex
from typing import Any

from ageval.harbor.reward import parse_reward_json, parse_reward_text, verdict_from_rewards
from ageval_sdk.errors import ScriptError

_REWARD_JSON = "/logs/verifier/reward.json"
_REWARD_TEXT = "/logs/verifier/reward.txt"


async def evaluate(inputs: dict[str, Any]) -> dict[str, Any]:
    """Return PASS or FAIL. A missing reward is ``harbor_reward_missing``."""
    scoring = inputs.get("scoring")
    if scoring is None:
        raise ScriptError("harbor_reward_missing", "scoring host is not available")
    params = inputs.get("parameters") if isinstance(inputs.get("parameters"), dict) else {}
    env_name = str(params.get("harbor_scoring_env") or "verifier")
    script = str(params.get("harbor_test_script") or "/tests/test.sh")
    await scoring.exec(env_name, ["sh", script])
    rewards = await _read_rewards(scoring, env_name, params)
    return verdict_from_rewards(rewards)


async def _read_rewards(scoring: Any, env_name: str, params: dict[str, Any]) -> dict[str, Any]:
    json_path = str(params.get("harbor_reward_json") or _REWARD_JSON)
    text_path = str(params.get("harbor_reward_text") or _REWARD_TEXT)
    raw_json = await _read_file(scoring, env_name, json_path)
    if raw_json is not None:
        try:
            return parse_reward_json(raw_json)
        except ValueError as exc:
            raise ScriptError("harbor_reward_invalid", str(exc)) from exc
    raw_text = await _read_file(scoring, env_name, text_path)
    if raw_text is None:
        raise ScriptError(
            "harbor_reward_missing",
            "tests/test.sh wrote neither reward.json nor reward.txt",
        )
    try:
        return parse_reward_text(raw_text)
    except ValueError as exc:
        raise ScriptError("harbor_reward_invalid", str(exc)) from exc


async def _read_file(scoring: Any, env_name: str, path: str) -> str | None:
    result = await scoring.exec(env_name, ["sh", "-c", f"cat {shlex.quote(path)}"])
    if int(result.exit_code) != 0:
        return None
    return str(result.stdout or "")
