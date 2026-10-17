"""``reasoning.effort: max`` is rewritten to the pin's highest tier at lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.helpers.lock import CONFIG_MIN, job_document, lock_standalone

from ageval.config.errors import ConfigError
from ageval.config.model import thaw
from ageval.model import resolve_model
from ageval.model.errors import ModelConfigError
from ageval.model.pin import resolve_effort_max

TASK_YAML = (CONFIG_MIN / "tasks" / "minimal" / "task.yaml").read_text(encoding="utf-8")

_PIN: dict[str, Any] = {
    "format": "ageval.model-pin/1",
    "prefixes": ["openai", "dashscope"],
    "models": {
        "acme/thinker": {"reasoning_options": [{"type": "effort", "values": ["low", "high"]}]},
        "acme/literal-max": {"reasoning_options": [{"type": "effort", "values": ["low", "max"]}]},
        "acme/empty": {"reasoning_options": []},
    },
    "aliases": {"thinker-alias": "acme/thinker"},
    "lookup": {"qwen3.8-max": ["acme/thinker"]},
}


def _solver(model_id: str, effort: str) -> dict[str, Any]:
    return {
        "executor": "acp",
        "model": {"id": model_id, "reasoning": {"effort": effort}},
        "options": {"entry": "codex"},
        "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
    }


def _lock(root: Path, profile: dict[str, Any]) -> Any:
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (root / "run.py").write_text("#\n", encoding="utf-8")
    (root / "evaluator.py").write_text("#\n", encoding="utf-8")
    return lock_standalone(root, "minimal", job=job_document({"solver": profile}))


def _install_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ageval.model.pin.load_model_pin", lambda: _PIN)


def test_lock_rewrites_max_to_the_highest_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_pin(monkeypatch)
    locked = _lock(tmp_path / "task", _solver("acme/thinker", "max"))
    row = thaw(locked.agent_profiles)[0]
    overlay = thaw(locked.job_overlay)["agent_profiles"]["solver"]
    assert row["model"]["reasoning"]["effort"] == "high"
    assert overlay["model"]["reasoning"]["effort"] == "high"


def test_lock_keeps_max_when_that_is_the_highest_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_pin(monkeypatch)
    locked = _lock(tmp_path / "task", _solver("acme/literal-max", "max"))
    row = thaw(locked.agent_profiles)[0]
    assert row["model"]["reasoning"]["effort"] == "max"


def test_gateway_prefix_joins_before_the_tier_is_chosen() -> None:
    assert resolve_effort_max("openai/dashscope/qwen3.8-max", pin=_PIN) == "high"
    assert resolve_effort_max("thinker-alias", pin=_PIN) == "high"


def test_missing_effort_list_fails_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_pin(monkeypatch)
    with pytest.raises(ConfigError) as caught:
        _lock(tmp_path / "task", _solver("acme/empty", "max"))
    assert caught.value.error_code == "model_config"
    assert "concrete tier" in caught.value.message
    assert caught.value.location is not None
    assert caught.value.location.endswith("/agent_profiles/solver")


def test_unknown_model_fails_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pin(monkeypatch)
    with pytest.raises(ConfigError) as caught:
        _lock(tmp_path / "task", _solver("acme/missing", "max"))
    assert caught.value.error_code == "model_config"
    assert "concrete tier" in caught.value.message


def test_concrete_tiers_are_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pin(monkeypatch)
    high = _lock(tmp_path / "high", _solver("acme/thinker", "high"))
    none = _lock(tmp_path / "none", _solver("acme/empty", "none"))
    assert thaw(high.agent_profiles)[0]["model"]["reasoning"]["effort"] == "high"
    assert thaw(none.agent_profiles)[0]["model"]["reasoning"]["effort"] == "none"


def test_absent_pin_file_keeps_the_token_at_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ageval.model.pin.load_model_pin", lambda: None)
    spec = resolve_model({"id": "m", "reasoning": {"effort": "max"}})
    assert spec.reasoning_effort == "max"


def test_present_pin_without_the_model_fails_resolve() -> None:
    with pytest.raises(ModelConfigError, match="concrete tier"):
        resolve_effort_max("not-in-the-committed-pin", strict=False)
