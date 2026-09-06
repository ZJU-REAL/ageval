"""Upload path preserves / recomputes pass@k before POST (#60 A4 / B2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ageval.application.composition import build_results_commands
from ageval.application.registry_ops.results_command import (
    ResultsCommands,
    _run_ids_from_task_refs,
)
from ageval.application.suite.document import metrics_and_refs as _suite_metrics_and_refs

_results = build_results_commands()
get_suite_result = _results.get_suite_result
upload_suite_result = _results.upload_suite_result


def _write_summary(db: Path, suite_run_id: str, summary: dict[str, Any]) -> Path:
    suite_dir = db / ".ageval" / "suite-runs" / suite_run_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": suite_run_id,
        "dataset_id": "test/db",
        "dataset_version": "0.1.0",
        "exit_code": 0,
        **summary,
    }
    (suite_dir / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return suite_dir


def test_suite_metrics_and_refs_recompute_k_for_local_get(tmp_path: Path) -> None:
    db = tmp_path / "db"
    db.mkdir()
    (db / "ageval.yaml").write_text(
        "format: ageval.dataset/1\nid: test/db\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    suite_run_id = "suite_recompute_local"
    _write_summary(
        db,
        suite_run_id,
        {
            "n_attempts": 2,
            "attempts": [
                {"task_id": "a", "attempt_index": 0, "status": "PASS", "run_id": "a0"},
                {"task_id": "a", "attempt_index": 1, "status": "PASS", "run_id": "a1"},
            ],
            "tasks": [
                {
                    "task_id": "a",
                    "status": "PASS",
                    "score": 1.0,
                    "n": 2,
                    "c": 2,
                    "run_id": "a0",
                },
            ],
            # Intentionally missing k metrics
            "metrics": {
                "pass_rate": 1.0,
                "mean_score": 1.0,
                "n_tasks": 1,
                "n_pass": 1,
                "n_fail": 0,
                "n_error": 0,
                "missing_score_as": 0.0,
            },
        },
    )
    got = get_suite_result(suite_run_id, local=db)
    assert got["metrics"]["pass_at_k"]["2"]["value"] == pytest.approx(1.0)
    assert got["metrics"]["n_attempts"] == 2
    assert got["task_refs"][0]["attempt_run_ids"] == ["a0", "a1"]
    assert got["task_refs"][0]["n"] == 2
    assert got["task_refs"][0]["c"] == 2


def test_run_ids_prefers_attempt_run_ids() -> None:
    refs = [
        {
            "task_id": "a",
            "run_id": "a0",
            "attempt_run_ids": ["a0", "a1", "a2"],
        },
        {"task_id": "b", "run_id": "b0"},
    ]
    assert _run_ids_from_task_refs(refs) == ["a0", "a1", "a2", "b0"]


def test_upload_payload_includes_recomputed_pass_at_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "db-up"
    db.mkdir()
    # Minimal dataset root so upload can resolve id when needed
    (db / "ageval.yaml").write_text(
        "format: ageval.dataset/1\nid: test/db\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    suite_run_id = "suite_upload_k"
    _write_summary(
        db,
        suite_run_id,
        {
            "n_attempts": 2,
            "attempts": [
                {"task_id": "a", "attempt_index": 0, "status": "PASS", "run_id": "a0"},
                {"task_id": "a", "attempt_index": 1, "status": "FAIL", "run_id": "a1"},
                {"task_id": "b", "attempt_index": 0, "status": "PASS", "run_id": "b0"},
                {"task_id": "b", "attempt_index": 1, "status": "PASS", "run_id": "b1"},
            ],
            "tasks": [
                {"task_id": "a", "status": "PASS", "score": 0.5, "n": 2, "c": 1, "run_id": "a0"},
                {"task_id": "b", "status": "PASS", "score": 1.0, "n": 2, "c": 2, "run_id": "b0"},
            ],
            "task_refs": [
                {"task_id": "a", "status": "PASS", "score": 0.5, "run_id": "a0"},
                {"task_id": "b", "status": "PASS", "score": 1.0, "run_id": "b0"},
            ],
            # legacy metrics only
            "metrics": {
                "pass_rate": 1.0,
                "mean_score": 0.75,
                "n_tasks": 2,
                "n_pass": 2,
                "n_fail": 0,
                "n_error": 0,
                "missing_score_as": 0.0,
            },
        },
    )

    captured: dict[str, Any] = {}

    def fake_upload_suite(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "suite_run_id": kwargs["suite_run_id"],
            "dataset_id": kwargs["dataset_id"],
            "dataset_version": kwargs["dataset_version"],
            "pass_rate": kwargs["pass_rate"],
            "mean_score": kwargs["mean_score"],
            "metrics": kwargs["metrics"],
            "task_refs": kwargs["task_refs"],
            "blob_digest": kwargs["blob_digest"],
            "note": "per-task evaluator verdicts only; no suite-level PASS",
        }

    mock_client = MagicMock()
    mock_client.upload_suite.side_effect = lambda **kw: fake_upload_suite(**kw)
    cmds = ResultsCommands(client_factory=lambda **_kw: mock_client)

    out = cmds.upload_suite_result(db, suite_run_id=suite_run_id)
    assert out["ok"] is True
    metrics = captured["metrics"]
    assert "pass_at_k" in metrics
    assert "pass_power_k" in metrics
    assert metrics["n_attempts"] == 2
    # a: 0.5, b: 1.0 → mean 0.75 for pass@1
    assert metrics["pass_at_k"]["1"]["value"] == pytest.approx(0.75)
    refs = captured["task_refs"]
    by_id = {str(r["task_id"]): r for r in refs}
    assert by_id["a"]["attempt_run_ids"] == ["a0", "a1"]
    assert by_id["b"]["n"] == 2
    assert by_id["b"]["c"] == 2
    # fingerprint identity fields must not include pass@k (not sent as fingerprint keys)
    assert "config_fingerprint" not in metrics


def test_suite_metrics_and_refs_unit() -> None:
    summary = {
        "n_attempts": 2,
        "attempts": [
            {"task_id": "a", "attempt_index": 0, "status": "PASS", "run_id": "a0"},
            {"task_id": "a", "attempt_index": 1, "status": "PASS", "run_id": "a1"},
        ],
        "tasks": [
            {"task_id": "a", "status": "PASS", "score": 1.0, "n": 2, "c": 2, "run_id": "a0"},
        ],
        "metrics": {"pass_rate": 1.0, "mean_score": 1.0, "n_tasks": 1},
    }
    metrics, refs = _suite_metrics_and_refs(summary)
    assert metrics["pass_at_k"]["2"]["value"] == pytest.approx(1.0)
    assert refs[0]["attempt_run_ids"] == ["a0", "a1"]
