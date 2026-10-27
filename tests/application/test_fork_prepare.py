"""Fork preparation rejects unsafe cuts before an environment starts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.evidence.test_fork_cuts import _attempt, _header, _phase
from typer.testing import CliRunner

from ageval.application.fork import ForkRejection, ForkRequest, copy_fork_prefix, prepare_fork
from ageval.cli.main import app
from ageval.evidence.activity import ActivityLog


def _lock(
    role: str = "solver", model: str = "model-a", environment: str = "docker"
) -> dict[str, object]:
    return {
        "format": "ageval.lock/1",
        "dataset_id": "demo",
        "dataset_version": "0.1.0",
        "task_id": "demo",
        "environment": environment,
        "digest": "sha256:source",
        "job_overlay": {
            "agent_profiles": {
                role: {
                    "executor": "miniswe",
                    "model": {"id": model, "api": "chat"},
                    "options": {"entry": "mini"},
                }
            }
        },
    }


def _source(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    attempt = _attempt(dataset / ".ageval" / "runs")
    (attempt / "lock.json").write_text(json.dumps(_lock()), encoding="utf-8")
    return dataset


def test_prepare_accepts_model_switch_and_rejects_environment(tmp_path: Path) -> None:
    dataset = _source(tmp_path)
    plan = prepare_fork(
        dataset,
        ForkRequest("attempt01", 6, "model-b"),
        child_lock=_lock(model="model-b"),
    )
    assert plan.continuation_model == "model-b"
    assert plan.source_model == "model-a"
    assert plan.changes[0]["from"] == "model-a"
    assert plan.changes[0]["to"] == "model-b"
    with pytest.raises(ForkRejection) as exc:
        prepare_fork(
            dataset,
            ForkRequest("attempt01", 6, "model-b"),
            child_lock=_lock(model="model-b", environment="local"),
        )
    assert exc.value.error_code == "fork_config_rejected"


def test_prepare_rejects_sealed_cut(tmp_path: Path) -> None:
    dataset = _source(tmp_path)
    attempt = dataset / ".ageval" / "runs" / "attempt01"
    log = ActivityLog.open(attempt / "activity.jsonl")
    log.append(
        request_id="phase_seal_run",
        kind="phase",
        status="completed",
        payload=_phase("seal_run", seq=7),
    )
    with pytest.raises(ForkRejection) as exc:
        prepare_fork(
            dataset,
            ForkRequest("attempt01", 7, "model-b"),
            child_lock=_lock(model="model-b"),
        )
    assert exc.value.error_code == "solver_sealed"


def test_copy_prefix_stops_at_cut_and_rewrites_identity(tmp_path: Path) -> None:
    dataset = _source(tmp_path)
    source = dataset / ".ageval" / "runs" / "attempt01"
    child = tmp_path / "child"
    log = copy_fork_prefix(
        source,
        child,
        seq=6,
        run_id="run-child",
        trial_id="trial-child",
        attempt_id="attempt-child",
        digest="sha256:child",
    )
    header = log.header()
    assert header is not None
    assert header.payload["attempt_id"] == "attempt-child"
    assert header.payload["environment_handle"] is None
    assert header.payload["locked_config_digest"] == "sha256:child"
    assert all(record.seq <= 6 for record in log.records)
    assert all(
        record.payload.get("inherited") is True
        for record in log.records
        if record.kind != "attempt"
    )
    assert (child / "checkpoints" / "seq_000006.json").is_file()
    assert not (child / "checkpoints" / "seq_000007.json").exists()


def test_cli_rejects_fork_with_resume_or_agent() -> None:
    runner = CliRunner()
    resumed = runner.invoke(
        app,
        [
            "run",
            "dataset",
            "--task",
            "demo",
            "--fork",
            "attempt01",
            "--checkpoint",
            "6",
            "--model",
            "model-b",
            "--resume",
            "attempt01",
        ],
    )
    assert resumed.exit_code == 2
    assert "fork_resume_exclusive" in resumed.stderr
    harness = runner.invoke(
        app,
        [
            "run",
            "dataset",
            "--task",
            "demo",
            "--fork",
            "attempt01",
            "--checkpoint",
            "6",
            "--model",
            "model-b",
            "--agent",
            "pi",
        ],
    )
    assert harness.exit_code == 2
    assert "fork_harness_fixed" in harness.stderr


def test_inherited_phase_elapsed_is_not_charged(tmp_path: Path) -> None:
    log = ActivityLog.open(tmp_path / "activity.jsonl")
    log.append(request_id="att", kind="attempt", status="completed", payload=_header())
    log.append(
        request_id="phase_run",
        kind="phase",
        status="completed",
        payload={**_phase("run", seq=2), "elapsed_ms": 5000, "inherited": True},
    )
    assert log.phase_elapsed_ms("run") == 0
