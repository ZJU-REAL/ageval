"""Suite task table pages one slice and keeps a pace row for every task."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from ageval.viewer import jobs
from ageval.viewer.server import make_handler

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "tests" / "fixtures" / "datasets" / "suite-min"
JOB_ID = "suite_page"


def _clean_db(tmp_path: Path) -> Path:
    db = tmp_path / "db"
    shutil.copytree(SUITE, db, ignore=shutil.ignore_patterns(".ageval"))
    return db


def _seed(db: Path) -> None:
    suite_dir = db / ".ageval" / "suite-runs" / JOB_ID
    suite_dir.mkdir(parents=True)
    summary = {
        "schema": "ageval.suite.summary/1",
        "suite_run_id": JOB_ID,
        "dataset_id": "test/suite-min",
        "dataset_version": "0.1.0",
        "created_at": "2026-08-30T10:00:00Z",
        "task_ids": ["alpha", "beta", "gamma", "delta"],
        "attempts": [
            {
                "task_id": "alpha",
                "attempt_index": 0,
                "status": "PASS",
                "score": 0.2,
                "run_id": "run_a",
            },
            {"task_id": "beta", "attempt_index": 0, "status": "ERROR", "run_id": "run_b"},
            {
                "task_id": "gamma",
                "attempt_index": 0,
                "status": "FAIL",
                "score": 0.9,
                "run_id": "run_c",
            },
            {
                "task_id": "delta",
                "attempt_index": 0,
                "status": "PASS",
                "score": 0.5,
                "run_id": "run_d",
            },
        ],
        "tasks": [
            {"task_id": "alpha", "status": "PASS", "score": 0.2, "run_id": "run_a"},
            {
                "task_id": "beta",
                "status": "ERROR",
                "score": None,
                "run_id": "run_b",
                "error": {"title": "disk full", "message": "no space"},
            },
            {"task_id": "gamma", "status": "FAIL", "score": 0.9, "run_id": "run_c"},
            {"task_id": "delta", "status": "PASS", "score": 0.5, "run_id": "run_d"},
        ],
        "task_refs": [
            {"task_id": "alpha", "status": "PASS", "score": 0.2, "run_id": "run_a"},
            {"task_id": "beta", "status": "ERROR", "score": None, "run_id": "run_b"},
            {"task_id": "gamma", "status": "FAIL", "score": 0.9, "run_id": "run_c"},
            {"task_id": "delta", "status": "PASS", "score": 0.5, "run_id": "run_d"},
        ],
        "metrics": {"n_tasks": 4, "n_pass": 2, "n_fail": 1, "n_error": 1},
        "exit_code": 0,
        "status": "complete",
    }
    (suite_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")


def test_unpaged_job_still_returns_every_task(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed(db)
    payload = jobs.get_job(db, JOB_ID)
    assert [row["task_id"] for row in payload["tasks"]] == ["alpha", "beta", "gamma", "delta"]
    assert payload["task_count"] == 4
    assert "pace" not in payload
    assert "page" not in payload


def test_task_page_is_a_slice_and_pace_covers_the_suite(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed(db)
    first = jobs.get_job(db, JOB_ID, page=1, page_size=2, sort="task_id", direction="asc")
    assert [row["task_id"] for row in first["tasks"]] == ["alpha", "beta"]
    assert [row["task_id"] for row in first["pace"]] == ["alpha", "beta", "gamma", "delta"]
    assert first["task_count"] == 4
    assert first["total"] == 4
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert first["reasons"] == ["disk full"]

    second = jobs.get_job(db, JOB_ID, page=2, page_size=2, sort="task_id", direction="asc")
    assert [row["task_id"] for row in second["tasks"]] == ["delta", "gamma"]
    assert len(second["pace"]) == 4

    clamped = jobs.get_job(db, JOB_ID, page=9, page_size=2, sort="task_id", direction="asc")
    assert clamped["page"] == 2
    assert [row["task_id"] for row in clamped["tasks"]] == ["delta", "gamma"]


def test_task_page_sort_and_reason_do_not_shrink_pace(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed(db)
    by_score = jobs.get_job(db, JOB_ID, page=1, page_size=2, sort="score", direction="desc")
    assert [row["task_id"] for row in by_score["tasks"]] == ["gamma", "delta"]
    assert len(by_score["pace"]) == 4

    lowest = jobs.get_job(db, JOB_ID, page=2, page_size=2, sort="score", direction="asc")
    assert [row["task_id"] for row in lowest["tasks"]] == ["gamma", "beta"]

    only = jobs.get_job(db, JOB_ID, page=1, page_size=2, reason="disk full")
    assert [row["task_id"] for row in only["tasks"]] == ["beta"]
    assert only["total"] == 1
    assert [row["task_id"] for row in only["pace"]] == ["alpha", "beta", "gamma", "delta"]


def test_http_task_page_query(tmp_path: Path) -> None:
    db = _clean_db(tmp_path)
    _seed(db)
    handler = make_handler(db, None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        query = f"page=1&page_size=2&sort=score&dir=desc&reason={quote('disk full')}"
        with urlopen(f"http://127.0.0.1:{port}/api/jobs/{JOB_ID}?{query}", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert [row["task_id"] for row in payload["tasks"]] == ["beta"]
        assert len(payload["pace"]) == 4
        with urlopen(f"http://127.0.0.1:{port}/api/jobs/{JOB_ID}", timeout=5) as resp:
            full = json.loads(resp.read().decode("utf-8"))
        assert len(full["tasks"]) == 4
        assert "pace" not in full
    finally:
        server.shutdown()
