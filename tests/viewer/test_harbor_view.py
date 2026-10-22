"""ageval view binds a Harbor task or task-set without --layout."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.application.local_jobs.listing import commands_for, list_jobs
from ageval.viewer.browse import dataset_overview
from ageval.viewer.session import open_view


def _task(parent: Path, name: str) -> Path:
    task = parent / name
    (task / "tests").mkdir(parents=True)
    (task / "task.toml").write_text("[agent]\ntimeout_sec = 30\n", encoding="utf-8")
    (task / "instruction.md").write_text("say hello\n", encoding="utf-8")
    (task / "tests" / "test.sh").write_text("exit 0\n", encoding="utf-8")
    return task


def _summary(root: Path, job_id: str) -> None:
    suite = root / ".ageval" / "suite-runs" / job_id
    suite.mkdir(parents=True)
    (suite / "summary.json").write_text(
        json.dumps(
            {
                "schema": "ageval.suite.summary/1",
                "suite_run_id": job_id,
                "dataset_id": root.name,
                "dataset_version": "1",
                "tasks": [{"task_id": root.name, "status": "PASS", "score": 1.0}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_view_opens_a_harbor_task_and_lists_its_suite(tmp_path: Path) -> None:
    root = _task(tmp_path, "demo-task")
    _summary(root, "ab12cd34")
    session = open_view(root)
    assert session.mode == "dataset"
    assert session.landing == "jobs"
    opened = session.datasets[0]
    assert opened.dataset_id == "demo-task"
    assert opened.version == "1"
    assert opened.task_count == 1
    assert opened.root == root.resolve()

    overview = dataset_overview(root)
    assert overview["task_ids"] == ["demo-task"]
    assert overview["task_count"] == 1

    jobs = list_jobs(root)
    assert jobs["dataset_id"] == "demo-task"
    assert jobs["version"] == "1"
    assert [item["job_id"] for item in jobs["items"]] == ["ab12cd34"]
    assert jobs["commands"]["run_suite"].endswith(" --layout harbor")
    assert "--task" not in jobs["commands"]["lock_suite_hint"]
    assert "--layout harbor" in jobs["commands"]["tasks"]


def test_view_opens_a_harbor_task_set(tmp_path: Path) -> None:
    root = tmp_path / "terminal-bench"
    _task(root, "alpha")
    _task(root, "beta")
    session = open_view(root)
    assert session.mode == "dataset"
    assert session.datasets[0].dataset_id == "terminal-bench"
    assert session.datasets[0].task_count == 2
    jobs = list_jobs(root)
    assert jobs["dataset_id"] == "terminal-bench"
    assert "--layout harbor" in jobs["commands"]["run_suite"]
    assert jobs["commands"]["lock_suite_hint"].endswith("--task <task_id>")
    task_cmds = commands_for(root, task_id="alpha")
    assert "--layout harbor" in task_cmds["run_task"]
    assert "--task alpha" in task_cmds["run_task"]


def test_view_parent_lists_a_harbor_child(tmp_path: Path) -> None:
    parent = tmp_path / "datasets"
    _task(parent, "demo-task")
    (parent / "other").mkdir(parents=True)
    session = open_view(parent)
    assert session.mode == "parent"
    assert [item.key for item in session.datasets] == ["demo-task"]


def test_view_does_not_bind_a_harbor_registry_index(tmp_path: Path) -> None:
    root = tmp_path / "index"
    child = _task(root, "demo-task")
    (root / "registry.json").write_text("{}\n", encoding="utf-8")
    session = open_view(root)
    assert session.mode == "parent"
    assert session.datasets[0].root == child.resolve()
