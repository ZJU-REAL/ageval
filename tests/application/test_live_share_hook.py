"""Suite execution patches a bound live share without owning the verdict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ageval.application.registry_ops.live_share import push_bound_live_share
from ageval.application.suite.suite_run import execute_suite_run, plan_suite_run

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"


@pytest.mark.asyncio
async def test_suite_run_pushes_on_job_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def fake_push(_root, _suite_run_id, *, include_files: bool):
        calls.append(include_files)
        return {"ok": False, "error": "registry_unavailable"}

    monkeypatch.setattr(
        "ageval.application.registry_ops.live_share.push_bound_live_share",
        fake_push,
    )
    plan = plan_suite_run(SUITE, task_id="alpha", n_attempts=1, max_concurrent_tasks=1)

    async def runner(root, task_id, *, overrides=None, profiles_path=None, **kwargs):  # noqa: ANN001
        del overrides, profiles_path, kwargs
        run_id = f"sha256_live_{task_id}"
        abs_run = Path(root) / ".ageval" / "runs" / run_id
        abs_run.mkdir(parents=True, exist_ok=True)
        result = type(
            "Result",
            (),
            {"status": "PASS", "score": 1.0, "evidence_path": str(abs_run), "logs": str(abs_run)},
        )()
        return 0, result

    summary = await execute_suite_run(plan, run_fn=runner)
    assert summary.get("status") == "complete"
    assert True in calls


def test_offline_push_keeps_the_token_binding(tmp_path: Path) -> None:
    suite = tmp_path / ".ageval" / "suite-runs" / "suite0001"
    suite.mkdir(parents=True)
    (suite / "summary.json").write_text(
        json.dumps(
            {
                "suite_run_id": "suite0001",
                "dataset_id": "acme/demo",
                "dataset_version": "0.1.0",
                "status": "running",
                "task_refs": [],
            }
        ),
        encoding="utf-8",
    )
    (suite / "live-share.json").write_text(
        json.dumps(
            {
                "mode": "live",
                "token": "token-1",
                "registry_url": "http://127.0.0.1:9",
                "hub_url": "https://hub.example",
                "sources": {},
                "last_error": "",
            }
        ),
        encoding="utf-8",
    )
    result = push_bound_live_share(tmp_path, "suite0001", include_files=False)
    assert result["ok"] is False
    assert result["token"] == "token-1"
    side = json.loads((suite / "live-share.json").read_text(encoding="utf-8"))
    assert side["token"] == "token-1"
    assert side["last_error"] not in {"", "not_found"}


def test_missing_sidecar_is_not_an_error(tmp_path: Path) -> None:
    assert push_bound_live_share(tmp_path, "missing", include_files=True)["skipped"] is True
