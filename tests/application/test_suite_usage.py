from __future__ import annotations

import json
from pathlib import Path

from ageval.application.model_directory import estimate_cost_usd, load_model_pin
from ageval.application.suite.suite_usage import (
    aggregate_usage,
    collect_suite_usage,
    merge_suite_usage,
    usage_from_trajectory,
)


def _write_traj(run_dir: Path, usage: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"type": "terminal", "usage": usage})
    (run_dir / "trajectory.jsonl").write_text(line + "\n", encoding="utf-8")


def test_usage_from_trajectory_last_terminal(tmp_path: Path) -> None:
    p = tmp_path / "trajectory.jsonl"
    p.write_text(
        json.dumps({"type": "assistant", "content": "hi"})
        + "\n"
        + json.dumps({"type": "terminal", "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
        + "\n"
        + json.dumps({"type": "terminal", "usage": {"prompt_tokens": 40, "completion_tokens": 8, "cost_usd": 0.02}})
        + "\n",
        encoding="utf-8",
    )
    got = usage_from_trajectory(p)
    assert got["prompt_tokens"] == 40
    assert got["completion_tokens"] == 8
    assert got["cost_usd"] == 0.02


def test_aggregate_usage_estimates_when_no_agent_cost() -> None:
    pin = load_model_pin()
    bag = aggregate_usage(
        [{"prompt_tokens": 1_000_000, "completion_tokens": 500_000}],
        overlay="deepseek/deepseek-v4-pro",
        pin=pin,
    )
    assert bag is not None
    assert bag["prompt_tokens"] == 1_000_000
    assert bag["completion_tokens"] == 500_000
    assert "cost_usd" not in bag
    if pin:
        assert bag.get("cost_source") == "estimated"
        assert isinstance(bag.get("cost_usd_estimated"), float)
        assert bag["cost_usd_estimated"] > 0
    else:
        assert bag.get("cost_source") == "missing"


def test_collect_suite_usage_from_run_dirs(tmp_path: Path) -> None:
    db = tmp_path / "ds"
    db.mkdir()
    (db / "ageval.yaml").write_text(
        "format: ageval.dataset/1\nid: t/ds\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    _write_traj(
        db / ".ageval" / "runs" / "r1",
        {"prompt_tokens": 100, "completion_tokens": 20},
    )
    (db / ".ageval" / "runs" / "r1" / "summary.json").write_text(
        json.dumps({"phase_timing": {"total_ms": 1500}}),
        encoding="utf-8",
    )
    summary = {
        "task_refs": [{"task_id": "a", "run_id": "r1"}],
        "job_overlay": {
            "agent_profiles": {"solver": {"model": "deepseek/deepseek-v4-pro"}}
        },
    }
    bag = collect_suite_usage(db, summary)
    assert bag is not None
    assert bag["prompt_tokens"] == 100
    assert bag["completion_tokens"] == 20
    assert bag["duration_s"] == 1.5


def test_merge_suite_usage_keeps_existing(tmp_path: Path) -> None:
    metrics = {
        "pass_rate": 1.0,
        "usage": {"prompt_tokens": 9, "cost_source": "reported", "cost_usd": 0.1},
    }
    out = merge_suite_usage(metrics, {"task_refs": []}, tmp_path)
    assert out["usage"]["prompt_tokens"] == 9
    assert out["usage"]["cost_usd"] == 0.1


def test_estimate_cost_usd_none_without_tokens() -> None:
    assert (
        estimate_cost_usd(
            prompt_tokens=None,
            completion_tokens=None,
            cached_tokens=None,
            overlay="deepseek/deepseek-v4-pro",
            pin=load_model_pin(),
        )
        is None
    )
