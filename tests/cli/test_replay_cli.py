"""Public replay command refuses before it starts an environment."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ageval.cli.main import app


def test_missing_source_exits_before_effects(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    result = CliRunner().invoke(app, ["replay", str(dataset), "--run", "missing", "--json"])
    assert result.exit_code == 2
    assert "unknown_run" in result.stdout
    assert not (dataset / ".ageval" / "runs").exists()
