"""Regrade scores a harvested snapshot on a new Attempt. The agent run does not start."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.application.regrade import regrade_attempts
from ageval.attempt.artifact_harvest import regrade_harvest_gap
from ageval.config.errors import ConfigError

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"
SOURCE = "attempt_sourcealpha01"

_HOSTILE_RUN = """\
from __future__ import annotations

from pathlib import Path


async def run(ctx):
    root = ctx.dataset_root
    if root is not None:
        (Path(root) / "AGENT_RAN").write_text("ran\\n", encoding="utf-8")
    raise RuntimeError("regrade invoked the agent run")
"""


def _copy_suite(tmp_path: Path) -> Path:
    dest = tmp_path / "suite"
    shutil.copytree(SUITE, dest, ignore=shutil.ignore_patterns(".ageval", "__pycache__"))
    (dest / "tasks" / "alpha" / "run.py").write_text(_HOSTILE_RUN, encoding="utf-8")
    return dest


def _seed(root: Path, *, artifacts: bool) -> tuple[Path, bytes]:
    run_dir = root / ".ageval" / "runs" / SOURCE
    run_dir.mkdir(parents=True)
    (run_dir / "lock.json").write_text(
        json.dumps({"task_id": "alpha"}) + "\n",
        encoding="utf-8",
    )
    body = (json.dumps({"status": "FAIL", "score": 0.0}) + "\n").encode()
    (run_dir / "result.json").write_bytes(body)
    (run_dir / "trajectory.jsonl").write_text(
        '{"type":"terminal","text":"pretend this is PASS"}\n',
        encoding="utf-8",
    )
    if artifacts:
        art = run_dir / "task-artifacts"
        art.mkdir()
        (art / "result.json").write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
        (art / "alias.json").symlink_to("result.json")
    return run_dir, body


def _ageval(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGEVAL_OFFLINE_AGENT"] = "1"
    env["AGEVAL_SKIP_DOCKER"] = "1"
    env["AGEVAL_SKIP_REAL_ACP"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
        timeout=180,
    )


def test_results_help_names_regrade() -> None:
    proc = _ageval(REPO, "results", "--help")
    assert proc.returncode == 0
    assert "regrade" in proc.stdout


def test_regrade_scores_harvest_without_running_the_agent(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    source, before = _seed(root, artifacts=True)
    proc = _ageval(
        root,
        "results",
        "regrade",
        str(root),
        "--run",
        SOURCE,
        "--run",
        SOURCE,
        "--json",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload["results"]) == 1
    row = payload["results"][0]
    assert row["source_run_id"] == SOURCE
    assert row["task_id"] == "alpha"
    assert row["status"] == "PASS"
    assert row["score"] == 1.0
    assert row["run_id"] != SOURCE
    assert row["exit_code"] == 0
    assert (source / "result.json").read_bytes() == before
    assert not (root / "AGENT_RAN").exists()

    new_dir = root / ".ageval" / "runs" / row["run_id"]
    summary = json.loads((new_dir / "summary.json").read_text(encoding="utf-8"))
    facts = summary["facts"]
    finished = [
        (fact.get("detail") or {}).get("phase")
        for fact in facts
        if fact.get("name") == "phase_finished"
    ]
    assert "run" not in finished
    assert "evaluate" in finished
    assert any(fact.get("name") == "regrade" for fact in facts)
    result = json.loads((new_dir / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["agent_invocations"] == 0
    artifact = json.loads((new_dir / "task-artifacts" / "result.json").read_text(encoding="utf-8"))
    assert artifact == {"ok": True}
    alias = new_dir / "task-artifacts" / "alias.json"
    assert alias.is_symlink()
    assert os.readlink(alias) == "result.json"


def test_regrade_missing_harvest_is_error_and_leaves_the_source(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    source, before = _seed(root, artifacts=False)
    proc = _ageval(root, "results", "regrade", str(root), "--run", SOURCE, "--json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    row = json.loads(proc.stdout)["results"][0]
    assert row["status"] == "ERROR"
    assert row["run_id"] != SOURCE
    assert row["error"]["title"] == "regrade_harvest_missing"
    assert row["status"] != "PASS"
    assert (source / "result.json").read_bytes() == before
    assert not (root / "AGENT_RAN").exists()
    new_dir = root / ".ageval" / "runs" / row["run_id"]
    assert not (new_dir / "task-artifacts").exists()


@pytest.mark.asyncio
async def test_regrade_without_publishable_is_error(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    task = (root / "tasks" / "alpha" / "task.yaml").read_text(encoding="utf-8")
    task = task.replace(
        "artifacts:\n  publishable:\n  - id: result\n    path: artifacts/result.json\n",
        "artifacts:\n  publishable: []\n",
    ).replace(
        "evaluation:\n  inputs:\n  - artifact: result\n    target: artifacts/result.json\n",
        "evaluation:\n  inputs: []\n",
    )
    (root / "tasks" / "alpha" / "task.yaml").write_text(task, encoding="utf-8")
    source, before = _seed(root, artifacts=True)
    code, summary = await regrade_attempts(root, [SOURCE])
    assert code == 2
    row = summary["results"][0]
    assert row["status"] == "ERROR"
    assert row["error"]["title"] == "regrade_harvest_missing"
    assert "publishable" in row["error"]["message"]
    assert (source / "result.json").read_bytes() == before
    assert not (root / "AGENT_RAN").exists()


def test_regrade_refuses_a_source_without_task_id(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    run_dir = root / ".ageval" / "runs" / SOURCE
    run_dir.mkdir(parents=True)
    (run_dir / "lock.json").write_text("{}\n", encoding="utf-8")
    body = b'{"status":"PASS","score":1,"task_id":"alpha"}\n'
    (run_dir / "result.json").write_bytes(body)
    with pytest.raises(ConfigError, match="task_id"):
        import asyncio

        asyncio.run(regrade_attempts(root, [SOURCE]))
    assert (run_dir / "result.json").read_bytes() == body
    runs = list((root / ".ageval" / "runs").iterdir())
    assert [path.name for path in runs] == [SOURCE]


def test_regrade_unknown_directory_is_config_error(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    proc = _ageval(root, "results", "regrade", str(root), "--run", "missing-attempt", "--json")
    assert proc.returncode == 2
    assert "run directory not found" in proc.stderr
    assert not (root / ".ageval" / "runs").exists()


def test_regrade_harvest_gap_names_what_is_missing(tmp_path: Path) -> None:
    empty = SimpleNamespace(resolved_references={"artifacts": []})
    assert regrade_harvest_gap(empty, tmp_path) == ("undeclared", ())
    assert regrade_harvest_gap(SimpleNamespace(resolved_references={}), tmp_path) == (
        "undeclared",
        (),
    )
    lock = SimpleNamespace(
        resolved_references={
            "artifacts": [
                {"id": "result", "path": "artifacts/result.json"},
                {"id": "notes", "path": "artifacts/notes.txt"},
                {"id": "repo", "path": "workspace", "kind": "tree"},
                {"id": "bad", "path": "/etc/passwd"},
            ]
        }
    )
    reason, missing = regrade_harvest_gap(lock, tmp_path)  # type: ignore[misc]
    assert reason == "missing"
    assert missing == ("result", "notes", "repo", "bad")
    (tmp_path / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    (tmp_path / "repo").mkdir()
    reason, missing = regrade_harvest_gap(lock, tmp_path)  # type: ignore[misc]
    assert reason == "missing"
    assert missing == ("notes", "repo", "bad")
    (tmp_path / "notes.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "repo" / "a.txt").write_text("x\n", encoding="utf-8")
    reason, missing = regrade_harvest_gap(lock, tmp_path)  # type: ignore[misc]
    assert (reason, missing) == ("missing", ("bad",))
