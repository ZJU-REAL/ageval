"""Public run of a Harbor tree: no run.py, suite summary, reward ERROR."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ageval.registry.cache import GIT_SOURCE_MARKER, PackageCache

PROFILES = """format: ageval.profiles/1
environment: local
agent_profiles:
  solver:
    executor: acp
    model: {id: entry-default}
    options:
      entry: codex
    extensions:
      - plugin: acp
      - plugin: local
"""


def _task(parent: Path, name: str) -> None:
    task = parent / name
    (task / "environment").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "task.toml").write_text("[agent]\ntimeout_sec = 30\n", encoding="utf-8")
    (task / "instruction.md").write_text("say hello\n", encoding="utf-8")
    (task / "environment" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    # exit 0 and write no reward: evaluate must be ERROR, not FAIL.
    (task / "tests" / "test.sh").write_text("exit 0\n", encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AGEVAL_OFFLINE_AGENT": "1"}
    env.setdefault("ZHIPU_API_KEY", "ci-offline-placeholder")
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def test_single_harbor_task_runs_without_task_scripts(tmp_path: Path) -> None:
    root = tmp_path / "demo-task"
    _task(tmp_path, "demo-task")
    (root / "profiles.yaml").write_text(PROFILES, encoding="utf-8")
    result = _run("run", str(root), "--layout", "harbor", "--json")
    assert result.returncode != 0, result.stderr
    document = json.loads(result.stdout)
    assert document["dataset_id"] == "demo-task"
    assert document["dataset_version"] == "1"
    assert document["tasks"][0]["task_id"] == "demo-task"
    assert document["tasks"][0]["status"] == "ERROR"
    assert not (root / "run.py").exists()
    summary = root / ".ageval" / "suite-runs"
    assert summary.is_dir()
    written = json.loads(next(summary.glob("*/summary.json")).read_text(encoding="utf-8"))
    from ageval.evidence.identity import dataset_identity

    assert dataset_identity(written, location="summary.json") == ("demo-task", "1")
    assert written.get("status") not in {"running", "in_progress"}


def test_harbor_task_set_runs_as_a_suite(tmp_path: Path) -> None:
    root = tmp_path / "terminal-bench"
    _task(root, "alpha")
    _task(root, "beta")
    (root / "profiles.yaml").write_text(PROFILES, encoding="utf-8")
    result = _run("run", str(root), "--layout", "harbor", "--json")
    assert result.returncode != 0, result.stderr
    document = json.loads(result.stdout)
    assert document["dataset_id"] == "terminal-bench"
    assert sorted(row["task_id"] for row in document["tasks"]) == ["alpha", "beta"]
    assert {row["status"] for row in document["tasks"]} == {"ERROR"}


def test_git_cache_hits_a_harbor_tree_without_ageval_yaml(tmp_path: Path) -> None:
    cache = PackageCache(tmp_path / "cache")
    commit = "a" * 40
    url = "https://example.com/harbor.git"
    entry = cache.git_entry_dir(url, commit, "tasks/demo")
    entry.mkdir(parents=True)
    (entry / "task.toml").write_text("", encoding="utf-8")
    (entry / GIT_SOURCE_MARKER).write_text(
        json.dumps(
            {
                "schema": "ageval.git-source/1",
                "git_url": url,
                "commit": commit,
                "git_ref": commit,
                "subdir": "tasks/demo",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    assert cache.lookup_git(url, commit, "tasks/demo") == entry
    bare = cache.git_entry_dir(url, commit, "empty")
    bare.mkdir(parents=True)
    (bare / GIT_SOURCE_MARKER).write_text("{}\n", encoding="utf-8")
    assert cache.lookup_git(url, commit, "empty") is None
