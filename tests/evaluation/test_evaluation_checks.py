"""Optional evaluator checks persist as evaluation/checks.json; not PASS."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.evaluation.bind import bind_result
from ageval.evidence.checks import (
    CHECKS_REL,
    CHECKS_SCHEMA,
    checks_document,
    package_script_rel,
    persist_evaluation_checks,
)
from ageval.evidence.store import AttemptEvidenceStore


def test_checks_document_absent_or_malformed_is_none() -> None:
    assert checks_document(None) is None
    assert checks_document("audit") is None
    assert checks_document([]) is None
    assert checks_document([{"title": "no id"}]) is None
    assert checks_document([{"id": ""}]) is None


def test_checks_document_keeps_known_fields_drops_unknown() -> None:
    doc = checks_document(
        [
            {
                "id": "audit",
                "title": "schema audit",
                "status": "FAIL",
                "score": 0,
                "script": "evaluation/audit.py",
                "environment": "audit",
                "exit_code": 2,
                "stdout": "mismatch",
                "stderr": "",
                "gold": "must-not-persist",
            },
            "skip-me",
            {"id": "files", "status": "PASS", "score": 1.0},
        ]
    )
    assert doc is not None
    assert doc["schema"] == CHECKS_SCHEMA
    assert [row["id"] for row in doc["checks"]] == ["audit", "files"]
    assert "gold" not in doc["checks"][0]
    assert doc["checks"][0]["status"] == "FAIL"
    assert doc["checks"][0]["exit_code"] == 2
    assert doc["checks"][1]["score"] == 1.0


def test_checks_document_truncates_streams() -> None:
    doc = checks_document([{"id": "big", "stdout": "x" * 80_000, "stderr": "y" * 80_000}])
    assert doc is not None
    row = doc["checks"][0]
    assert len(row["stdout"]) <= 65_536
    assert row["stdout"].endswith("…[truncated]")
    assert len(row["stderr"]) <= 65_536
    assert row["stderr"].endswith("…[truncated]")


def test_checks_document_drops_non_finite_score() -> None:
    doc = checks_document([{"id": "audit", "score": float("nan"), "status": "FAIL"}])
    assert doc is not None
    assert "score" not in doc["checks"][0]
    json.dumps(doc, allow_nan=False)


def test_persist_writes_only_when_well_formed(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    persist_evaluation_checks(store, {"status": "PASS", "score": 1.0})
    assert not (tmp_path / "run" / CHECKS_REL).exists()
    persist_evaluation_checks(
        store,
        {
            "status": "PASS",
            "score": 1.0,
            "checks": [{"id": "audit", "status": "FAIL", "score": 0.0}],
        },
    )
    path = tmp_path / "run" / CHECKS_REL
    assert path.is_file()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["schema"] == CHECKS_SCHEMA
    assert body["checks"][0]["id"] == "audit"


def test_persist_does_not_invent_from_facts(tmp_path: Path) -> None:
    store = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
    persist_evaluation_checks(
        store,
        {
            "status": "PASS",
            "score": 1.0,
            "metrics": {"exit_code": 0},
        },
    )
    assert not (tmp_path / "run" / CHECKS_REL).exists()


def test_package_script_rel_prefixes_task() -> None:
    assert package_script_rel("evaluation/audit.py", "script-score") == (
        "tasks/script-score/evaluation/audit.py"
    )
    assert (
        package_script_rel("tasks/script-score/evaluation/audit.py", "other")
        == "tasks/script-score/evaluation/audit.py"
    )
    assert package_script_rel("../secrets", "script-score") is None
    assert package_script_rel("", "script-score") is None
    assert package_script_rel("/etc/passwd", "script-score") is None
    assert package_script_rel("tasks/foo/../../secrets", "script-score") is None
    assert package_script_rel("tasks/alpha/.ageval/runs/x", "script-score") is None


def test_bind_result_ignores_checks_and_mismatch_is_allowed() -> None:
    result = bind_result(
        evaluator_raw={
            "status": "PASS",
            "score": 1.0,
            "metrics": {"exact": 1},
            "checks": [{"id": "audit", "status": "FAIL", "score": 0.0}],
        },
        kind="local",
        evidence_path="/tmp/evidence",
    )
    assert result.status == "PASS"
    assert result.score == 1.0
    assert result.metrics == {"exact": 1}
    fail_over_pass = bind_result(
        evaluator_raw={
            "status": "FAIL",
            "score": 0.0,
            "checks": [{"id": "audit", "status": "PASS", "score": 1.0}],
        },
        kind="local",
        evidence_path="/tmp/evidence",
    )
    assert fail_over_pass.status == "FAIL"
    assert fail_over_pass.score == 0.0
