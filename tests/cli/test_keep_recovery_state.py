"""Recovery-state retention flag and post-seal pruning policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.application.run import _prune_settled_recovery
from ageval.cli.recovery_state import resolve_keep_recovery_state
from ageval.config.errors import ConfigError


def test_run_registers_recovery_flag() -> None:
    import typer

    from ageval.cli.main import app

    commands = getattr(typer.main.get_command(app), "commands", None)
    assert isinstance(commands, dict)
    command = commands["run"]
    names = {
        opt
        for param in command.params
        for opt in (*param.opts, *getattr(param, "secondary_opts", ()))
    }
    assert "--keep-recovery-state" in names
    assert "--no-keep-recovery-state" in names


def test_flag_overrides_env() -> None:
    assert resolve_keep_recovery_state(True, env={"AGEVAL_KEEP_RECOVERY_STATE": "0"}) is True
    assert resolve_keep_recovery_state(False, env={"AGEVAL_KEEP_RECOVERY_STATE": "true"}) is False


def test_env_fallback_and_invalid() -> None:
    assert resolve_keep_recovery_state(None, env={}) is False
    assert resolve_keep_recovery_state(None, env={"AGEVAL_KEEP_RECOVERY_STATE": " yes "}) is True
    assert resolve_keep_recovery_state(None, env={"AGEVAL_KEEP_RECOVERY_STATE": "off"}) is False
    with pytest.raises(ConfigError) as exc:
        resolve_keep_recovery_state(None, env={"AGEVAL_KEEP_RECOVERY_STATE": "maybe"})
    assert exc.value.error_code == "invalid_override"
    assert exc.value.location == "AGEVAL_KEEP_RECOVERY_STATE"


def _settled(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir(exist_ok=True)
    (checkpoints / "seq_000001.json").write_text("{}", encoding="utf-8")
    (tmp_path / "activity.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trajectory.jsonl").write_text("{}\n", encoding="utf-8")


def test_unsealed_attempt_keeps_recovery_bundle(tmp_path: Path) -> None:
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "activity.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    _prune_settled_recovery(tmp_path, keep_workspace=False, keep_recovery_state=False)
    assert (tmp_path / "activity.jsonl").is_file()
    assert (tmp_path / "checkpoints").is_dir()
    assert (tmp_path / "state").is_dir()


def test_settled_policies_are_independent(tmp_path: Path) -> None:
    _settled(tmp_path)
    _prune_settled_recovery(tmp_path, keep_workspace=True, keep_recovery_state=False)
    assert not (tmp_path / "activity.jsonl").exists()
    assert not (tmp_path / "checkpoints").exists()
    assert (tmp_path / "state").is_dir()

    _settled(tmp_path)
    _prune_settled_recovery(tmp_path, keep_workspace=False, keep_recovery_state=True)
    assert (tmp_path / "activity.jsonl").is_file()
    assert (tmp_path / "checkpoints").is_dir()
    assert not (tmp_path / "state").exists()
