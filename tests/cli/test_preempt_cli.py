"""ageval preempt writes a request and does not signal the controller."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ageval.cli.main import app

_runner = CliRunner()


def test_preempt_writes_named_tasks_without_sigterm(tmp_path: Path, monkeypatch) -> None:
    suite_id = "abcd1234"
    (tmp_path / ".ageval" / "suite-runs" / suite_id).mkdir(parents=True)
    killed: list[int] = []
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append(pid))

    result = _runner.invoke(
        app,
        ["preempt", suite_id, "--dataset", str(tmp_path), "--task", "alpha", "--task", "beta"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "preempt_requested"
    assert payload["tasks"] == ["alpha", "beta"]
    assert "sigterm_sent" not in payload
    assert killed == []
    doc = json.loads(
        (tmp_path / ".ageval" / "suite-runs" / suite_id / "preempt.requested").read_text(
            encoding="utf-8"
        )
    )
    assert doc["schema"] == "ageval.suite.preempt/1"
    assert doc["tasks"] == ["alpha", "beta"]
    assert not (tmp_path / ".ageval" / "suite-runs" / suite_id / "cancel.requested").exists()


def test_preempt_unknown_suite_exits_2(tmp_path: Path) -> None:
    result = _runner.invoke(
        app,
        ["preempt", "missing1", "--dataset", str(tmp_path)],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"] == "unknown_suite"
