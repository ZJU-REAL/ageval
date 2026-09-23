"""Per-phase limit keys lock with the other limits and reject an unknown key once."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.lock import CONFIG_MIN, job_document, lock_standalone, lock_task

from ageval.config.errors import ConfigError
from ageval.config.model import thaw

SOLVER = {
    "executor": "acp",
    "model": "entry-default",
    "options": {"entry": "codex"},
    "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
}


def test_omitted_phase_clocks_take_the_defaults() -> None:
    locked = lock_task(CONFIG_MIN, "minimal")
    limits = thaw(locked.limits)
    assert limits["wall_time_seconds"] == 60
    assert limits["agent_invocations"] == 1
    assert limits["environment_seconds"] == 600
    assert limits["evaluate_seconds"] == 600


def test_authored_phase_clocks_are_kept(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    text = (CONFIG_MIN / "tasks" / "minimal" / "task.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "  wall_time_seconds: 60\n  agent_invocations: 1\n",
        "  wall_time_seconds: 60\n"
        "  environment_seconds: 12\n"
        "  evaluate_seconds: 34\n"
        "  agent_invocations: 1\n",
    )
    (root / "task.yaml").write_text(text, encoding="utf-8")
    (root / "run.py").write_text("#\n", encoding="utf-8")
    (root / "evaluator.py").write_text("#\n", encoding="utf-8")
    locked = lock_standalone(root, "minimal", job=job_document({"solver": dict(SOLVER)}))
    limits = thaw(locked.limits)
    assert limits["environment_seconds"] == 12
    assert limits["evaluate_seconds"] == 34


def test_unknown_limits_key_is_one_message(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    text = (CONFIG_MIN / "tasks" / "minimal" / "task.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "agent_invocations: 1\n", "agent_invocations: 1\n  environment_actions: 0\n"
    )
    (root / "task.yaml").write_text(text, encoding="utf-8")
    (root / "run.py").write_text("#\n", encoding="utf-8")
    (root / "evaluator.py").write_text("#\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        lock_standalone(root, "minimal", job=job_document({"solver": dict(SOLVER)}))
    assert caught.value.error_code == "invalid_schema"
    message = str(caught.value)
    assert message.count("unknown limits keys") == 1
    assert "environment_actions" in message
