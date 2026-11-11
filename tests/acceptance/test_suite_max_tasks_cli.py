"""Public CLI task-budget acceptance on real local Attempt filesystems."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/datasets/suite-min"
IDS = ["alpha", "beta", "delta-fail", "gamma"]


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return Path(
        shutil.copytree(FIXTURE, tmp_path / "dataset", ignore=shutil.ignore_patterns(".ageval"))
    )


def run_cli(dataset: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ageval.cli.main", "run", str(dataset), "--json", *args],
        env={**os.environ, "AGEVAL_OFFLINE_AGENT": "1", "TERM": "dumb", "NO_COLOR": "1"},
        cwd=dataset.parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def document(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip().startswith("{"), (result.stdout, result.stderr)
    return json.loads(result.stdout)


def test_capped_suite_and_resume_keep_real_evidence(dataset: Path) -> None:
    first_run = run_cli(dataset, "--max-tasks", "2", "-k", "2", "--max-concurrent-tasks", "3")
    assert first_run.returncode == 0, first_run.stderr
    first = document(first_run)
    assert first["task_ids"] == IDS[:2]
    assert first["max_tasks"] == 2
    assert first["status"] == "complete"
    assert not first.get("cancelled")
    assert len(first["attempts"]) == 4
    assert 1 < first["inflight_peak"] <= 3
    assert first["metrics"]["n_tasks"] == 2
    assert first["counts"]["error"] == 0
    evidence = dataset / ".ageval/runs"
    assert {json.loads(p.read_text())["task_id"] for p in evidence.glob("*/lock.json")} == set(
        IDS[:2]
    )
    original_results = {p: p.read_bytes() for p in evidence.glob("*/result.json")}
    assert len(original_results) == 4
    sid = first["suite_run_id"]

    second_run = run_cli(dataset, "--resume-suite", sid, "--max-tasks", "1", "-k", "2")
    assert second_run.returncode == 1, second_run.stderr
    second = document(second_run)
    assert second["status"] == "complete"
    assert second["task_ids"] == IDS[:3]
    assert second["max_tasks"] == 1
    assert second["new_attempts"] == 2
    assert second["metrics"]["n_tasks"] == 3
    assert second["counts"]["error"] == 0
    assert second["attempts"][:4] == first["attempts"]
    assert not second.get("cancelled")

    final_run = run_cli(dataset, "--resume-suite", sid, "-k", "2")
    assert final_run.returncode == 1, final_run.stderr
    final = document(final_run)
    assert final["task_ids"] == IDS
    assert len(final["attempts"]) == 8
    assert final["new_attempts"] == 2
    assert final["max_tasks"] is None
    assert final["config_fingerprint"] == first["config_fingerprint"]
    assert all(p.read_bytes() == data for p, data in original_results.items())
    assert all(a.get("phase") != "cancelled" for a in final["attempts"])


@pytest.mark.parametrize("cap", [None, "4", "10"])
def test_omit_or_large_cap_runs_every_task(dataset: Path, cap: str | None) -> None:
    result = run_cli(dataset, *(["--max-tasks", cap] if cap is not None else []))
    assert result.returncode == 1, result.stderr
    data = document(result)
    assert data["task_ids"] == IDS
    assert len(data["attempts"]) == 4
    assert data["status"] == "complete"


def test_partial_always_k_task_uses_one_budget(dataset: Path) -> None:
    first = document(run_cli(dataset, "--max-tasks", "1"))
    sid = first["suite_run_id"]
    resumed = document(run_cli(dataset, "--resume-suite", sid, "--max-tasks", "1", "-k", "3"))
    assert resumed["task_ids"] == ["alpha"]
    assert resumed["new_attempts"] == 2
    assert [a["attempt_index"] for a in resumed["attempts"]] == [0, 1, 2]
    assert resumed["attempts"][0] == first["attempts"][0]


def test_retry_errors_cap_preserves_other_errors(dataset: Path) -> None:
    for tid in ("beta", "gamma"):
        (dataset / "tasks" / tid / "evaluator.py").write_text(
            'def evaluate(inputs):\n    raise RuntimeError("scoring interrupted")\n',
            encoding="utf-8",
        )
    first = document(run_cli(dataset))
    assert first["counts"]["error"] == 2
    old = {a["task_id"]: a for a in first["attempts"]}
    result = run_cli(
        dataset, "--resume-suite", first["suite_run_id"], "--retry-errors", "--max-tasks", "1"
    )
    assert result.returncode == 2
    resumed = document(result)
    assert resumed["new_attempts"] == resumed["retried_attempts"] == 1
    current = {a["task_id"]: a for a in resumed["attempts"]}
    assert current["beta"]["run_id"] != old["beta"]["run_id"]
    assert current["beta"]["previous"][0]["run_id"] == old["beta"]["run_id"]
    assert current["gamma"] == old["gamma"]
    assert resumed["status"] == "complete"


@pytest.mark.parametrize("args", [("0",), ("-1",), ("text",), (), ("1", "--replace-slot")])
def test_invalid_budget_is_rejected_without_attempts(dataset: Path, args: tuple[str, ...]) -> None:
    result = run_cli(dataset, "--max-tasks", *args)
    assert result.returncode == 2
    assert "--max-tasks" in result.stderr
    assert not (dataset / ".ageval/runs").exists()
