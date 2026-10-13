"""Lock overlay resolve root follows agent_ref (design/14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.helpers.lock import lock_with_profiles

from ageval.agents import store
from ageval.config.errors import ConfigError
from ageval.config.model import thaw


@pytest.fixture(autouse=True)
def _ageval_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ageval-home"
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    return home


def _write_dataset(tmp: Path, *, overlay_files: dict[str, str] | None = None) -> Path:
    db = tmp / "db"
    (db / "tasks" / "t").mkdir(parents=True)
    (db / "ageval.yaml").write_text(
        "format: ageval.dataset/1\ndataset_id: example/overlays\nversion: '0.1.0'\n"
        "tasks:\n  root: tasks\n",
        encoding="utf-8",
    )
    (db / "profiles.yaml").write_text(
        "format: ageval.profiles/1\n"
        "environment: local\n"
        "agent_profiles:\n  solver:\n    executor: openai-http\n",
        encoding="utf-8",
    )
    task = db / "tasks" / "t"
    (task / "run.py").write_text("async def run(ctx):\n    pass\n", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(i):\n    return {}\n", encoding="utf-8")
    (task / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "format": "ageval.task/1",
                "task_id": "t",
                "parameters": {"models": {"default": "solver"}},
                "agent_profiles": [{"id": "solver"}, {"id": "user"}],
                "limits": {
                    "wall_time_seconds": 60,
                    "agent_invocations": 1,
                },
                "artifacts": {"publishable": []},
                "evaluation": {
                    "entrypoint": "evaluator:evaluate",
                    "inputs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    for rel, text in (overlay_files or {}).items():
        path = db / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return db


def _make_agent(
    tmp: Path,
    *,
    agent_id: str,
    version: str = "0.1.0",
    overlays: dict[str, str] | None = None,
    listed: list[str] | None = None,
) -> Path:
    pkg = tmp / f"agent-{agent_id.replace('/', '-')}"
    pkg.mkdir(parents=True)
    binding: dict[str, Any] = {"executor": "openai-http", "model": {"id": "none"}}
    if listed:
        binding["overlays"] = listed
    (pkg / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "format": "ageval.agent/1",
                "agent_id": agent_id.rsplit("/", 1)[-1],
                "version": version,
                "binding": binding,
            }
        ),
        encoding="utf-8",
    )
    for rel, text in (overlays or {}).items():
        path = pkg / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return pkg


def _lock(db: Path, agent_profiles: dict[str, dict[str, Any]]):
    return lock_with_profiles(
        db / "tasks" / "t",
        "t",
        agent_profiles,
    )


def test_lock_with_agent_ref_uses_agent_cache_not_dataset(tmp_path: Path) -> None:
    pkg = _make_agent(
        tmp_path,
        agent_id="official/xx",
        overlays={"overlays/skills/demo/SKILL.md": "# demo\n"},
        listed=["overlays/skills/demo"],
    )
    entry = store.install_from_path(pkg, agent_id="official/xx")
    db = _write_dataset(tmp_path)
    short = entry.digest[len("sha256:") :][:12]
    locked = _lock(
        db,
        {
            "*": {
                "executor": "openai-http",
                "model": {"id": "none"},
                "overlays": ["overlays/skills/demo"],
                "agent_ref": f"official/xx@0.1.0+sha256:{short}",
            }
        },
    )
    overlay = thaw(locked.job_overlay)
    assert overlay["agent_profiles"]["solver"]["overlays"] == ["overlays/skills/demo"]
    assert (db / "overlays").exists() is False


def test_lock_agent_ref_ignores_dataset_same_path(tmp_path: Path) -> None:
    pkg = _make_agent(tmp_path, agent_id="official/xx")
    entry = store.install_from_path(pkg, agent_id="official/xx")
    db = _write_dataset(
        tmp_path,
        overlay_files={"overlays/skills/demo/SKILL.md": "# dataset copy\n"},
    )
    short = entry.digest[len("sha256:") :][:12]
    with pytest.raises(ConfigError) as ei:
        _lock(
            db,
            {
                "solver": {
                    "executor": "openai-http",
                    "model": {"id": "none"},
                    "overlays": ["overlays/skills/demo"],
                    "agent_ref": f"official/xx@0.1.0+sha256:{short}",
                }
            },
        )
    assert ei.value.error_code == "missing_reference"


def test_lock_exact_role_without_overlays_not_attributed(tmp_path: Path) -> None:
    xx = _make_agent(
        tmp_path,
        agent_id="official/xx",
        overlays={"overlays/skills/demo/SKILL.md": "# demo\n"},
        listed=["overlays/skills/demo"],
    )
    yy = _make_agent(tmp_path, agent_id="official/yy")
    xx_entry = store.install_from_path(xx, agent_id="official/xx")
    yy_entry = store.install_from_path(yy, agent_id="official/yy")
    db = _write_dataset(tmp_path)
    xx_short = xx_entry.digest[len("sha256:") :][:12]
    yy_short = yy_entry.digest[len("sha256:") :][:12]
    locked = _lock(
        db,
        {
            "*": {
                "executor": "openai-http",
                "model": {"id": "none"},
                "overlays": ["overlays/skills/demo"],
                "agent_ref": f"official/xx@0.1.0+sha256:{xx_short}",
            },
            "user": {
                "executor": "openai-http",
                "model": {"id": "none"},
                "agent_ref": f"official/yy@0.1.0+sha256:{yy_short}",
            },
        },
    )
    overlay = thaw(locked.job_overlay)
    assert overlay["agent_profiles"]["solver"]["overlays"] == ["overlays/skills/demo"]
    assert overlay["agent_profiles"]["solver"]["agent_ref"].startswith("official/xx@")
    assert "overlays" not in overlay["agent_profiles"]["user"]
    assert overlay["agent_profiles"]["user"]["agent_ref"].startswith("official/yy@")


def test_handwritten_profiles_still_use_dataset_root(tmp_path: Path) -> None:
    db = _write_dataset(
        tmp_path,
        overlay_files={"overlays/AGENTS.md": "# hello\n"},
    )
    locked = _lock(
        db,
        {
            "solver": {
                "executor": "openai-http",
                "model": {"id": "none"},
                "overlays": ["overlays/AGENTS.md"],
            },
            "user": {"executor": "openai-http", "model": {"id": "none"}},
        },
    )
    overlay = thaw(locked.job_overlay)
    assert overlay["agent_profiles"]["solver"]["overlays"] == ["overlays/AGENTS.md"]
    assert "overlays" not in overlay["agent_profiles"]["user"]
