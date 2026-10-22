"""Harbor reward mapping: json wins, missing is not FAIL, zero is FAIL."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ageval.harbor.evaluate import evaluate
from ageval.harbor.reward import parse_reward_json, parse_reward_text, verdict_from_rewards
from ageval_sdk.errors import ScriptError


def test_json_preferred_and_pass_values() -> None:
    assert verdict_from_rewards(parse_reward_json('{"reward": 1}'))["status"] == "PASS"
    assert verdict_from_rewards(parse_reward_json('{"reward": 1.0}'))["status"] == "PASS"
    assert verdict_from_rewards(parse_reward_json('{"reward": true}'))["status"] == "PASS"
    failed = verdict_from_rewards(parse_reward_json('{"reward": 0, "style": 0.5}'))
    assert failed["status"] == "FAIL"
    assert failed["score"] == 0.0
    assert failed["metrics"]["style"] == 0.5
    assert verdict_from_rewards(parse_reward_json('{"reward": false}'))["status"] == "FAIL"


def test_text_reward_and_sole_key() -> None:
    assert verdict_from_rewards(parse_reward_text("1\n"))["status"] == "PASS"
    assert verdict_from_rewards(parse_reward_text("0"))["status"] == "FAIL"
    sole = verdict_from_rewards(parse_reward_json('{"accuracy": 1}'))
    assert sole["status"] == "PASS"


def test_invalid_reward_is_not_a_verdict() -> None:
    with pytest.raises(ValueError):
        parse_reward_text("nope")
    with pytest.raises(ValueError):
        verdict_from_rewards(parse_reward_json('{"a": 1, "b": 0}'))


class _Scoring:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.ran = False

    async def exec(self, name: str, argv: list[str]) -> SimpleNamespace:
        assert name == "verifier"
        if argv == ["sh", "/tests/test.sh"]:
            self.ran = True
            return SimpleNamespace(exit_code=0, stdout="", stderr="")
        command = argv[-1]
        for path, body in self.files.items():
            if path in command:
                return SimpleNamespace(exit_code=0, stdout=body, stderr="")
        return SimpleNamespace(exit_code=1, stdout="", stderr="missing")


@pytest.mark.asyncio
async def test_missing_reward_is_error_and_zero_is_fail() -> None:
    missing = _Scoring({})
    with pytest.raises(ScriptError) as exc:
        await evaluate({"scoring": missing, "parameters": {}})
    assert exc.value.title == "harbor_reward_missing"
    assert missing.ran

    zero = _Scoring({"/logs/verifier/reward.txt": "0\n"})
    verdict = await evaluate({"scoring": zero, "parameters": {}})
    assert verdict["status"] == "FAIL"
    assert verdict["score"] == 0.0

    preferred = _Scoring(
        {
            "/logs/verifier/reward.json": '{"reward": 1}',
            "/logs/verifier/reward.txt": "0\n",
        }
    )
    assert (await evaluate({"scoring": preferred, "parameters": {}}))["status"] == "PASS"
