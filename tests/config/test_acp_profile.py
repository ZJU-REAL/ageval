"""Config lock surface for executor: acp + options.entry (#59 agent_profiles)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.helpers.lock import lock_with_profiles

from ageval.config.errors import ConfigError
from ageval.config.model import thaw


def _write_pkg(root: Path, slot_ids: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "format": "ageval.task/1",
        "task_id": "acp-lock-test",
        "parameters": {},
        "agent_profiles": [{"id": s} for s in slot_ids],
        "limits": {
            "wall_time_seconds": 60,
            "agent_invocations": 2,
        },
        "artifacts": {"publishable": []},
        "evaluation": {
            "entrypoint": "evaluator:evaluate",
            "inputs": [],
        },
    }
    (root / "task.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    (root / "run.py").write_text("def run(ctx):\n    pass\n", encoding="utf-8")
    (root / "evaluator.py").write_text(
        "def evaluate(inputs):\n    return {'verdict': 'PASS'}\n", encoding="utf-8"
    )
    return root


def _lock(pkg: Path, agent_profiles: dict[str, dict[str, Any]]):
    return lock_with_profiles(pkg, "acp-lock-test", agent_profiles)


def test_acp_profile_lock_snapshot(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path / "pkg", ["opencode-acp"])
    lock = _lock(
        pkg,
        {
            "opencode-acp": {
                "executor": "acp",
                "model": {"id": "entry-default"},
                "extensions": [{"plugin": "acp", "options": {"entry": "opencode"}}],
            }
        },
    )
    profiles = thaw(lock.agent_profiles)
    assert profiles[0]["executor"] == "acp"
    assert profiles[0]["extensions"][0]["options"]["entry"] == "opencode"
    assert "_acp_lock" not in profiles[0]["extensions"][0]["options"]
    blob = str(profiles)
    assert "/opt/" not in blob
    assert "sk-" not in blob


def test_acp_missing_entry_fails(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path / "pkg", ["bad"])
    with pytest.raises(ConfigError):
        _lock(pkg, {"bad": {"executor": "acp", "model": {"id": "m"}}})


def test_acp_unknown_entry_fails(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path / "pkg", ["bad"])
    with pytest.raises(ConfigError):
        _lock(
            pkg,
            {
                "bad": {
                    "executor": "acp",
                    "model": {"id": "m"},
                    "extensions": [{"plugin": "acp", "options": {"entry": "not-registered"}}],
                }
            },
        )


def test_acp_reasoning_effort_survives_lock(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path / "pkg", ["solver"])
    lock = _lock(
        pkg,
        {
            "solver": {
                "executor": "acp",
                "model": {"id": "entry-default", "reasoning": {"effort": "high"}},
                "extensions": [{"plugin": "acp", "options": {"entry": "pi"}}],
            }
        },
    )
    profiles = thaw(lock.agent_profiles)
    assert profiles[0]["model"]["reasoning"]["effort"] == "high"
    assert "reasoning_effort" not in profiles[0]["extensions"][0]["options"]


def test_acp_flat_reasoning_effort_is_a_config_error(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path / "pkg", ["solver"])
    with pytest.raises(ConfigError, match="reasoning_effort"):
        _lock(
            pkg,
            {
                "solver": {
                    "executor": "acp",
                    "model": {"id": "entry-default"},
                    "extensions": [
                        {"plugin": "acp", "options": {"entry": "pi", "reasoning_effort": "high"}}
                    ],
                }
            },
        )


def test_acp_package_cannot_override_command(tmp_path: Path) -> None:
    pkg = _write_pkg(tmp_path / "pkg", ["bad"])
    with pytest.raises(ConfigError, match="belongs to the entry registry"):
        _lock(
            pkg,
            {
                "bad": {
                    "executor": "acp",
                    "model": {"id": "m"},
                    "extensions": [
                        {"plugin": "acp", "options": {"entry": "opencode", "command": ["evil"]}}
                    ],
                }
            },
        )
