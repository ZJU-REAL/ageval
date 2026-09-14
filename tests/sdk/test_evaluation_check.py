"""SDK evaluation_check builds the optional checks row. Not PASS."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ageval.evidence.checks import checks_document
from ageval_sdk import evaluation_check


def test_evaluation_check_requires_id() -> None:
    with pytest.raises(ValueError, match="id"):
        evaluation_check("")


def test_evaluation_check_row_shape() -> None:
    row = evaluation_check(
        "audit",
        title="schema audit",
        status="FAIL",
        score=0,
        script="evaluation/audit.py",
        environment="audit",
        exit_code=2,
        stdout="mismatch",
        stderr="",
    )
    assert row == {
        "id": "audit",
        "title": "schema audit",
        "status": "FAIL",
        "score": 0.0,
        "script": "evaluation/audit.py",
        "environment": "audit",
        "exit_code": 2,
        "stdout": "mismatch",
        "stderr": "",
    }
    doc = checks_document([row, evaluation_check("files", status="PASS", score=1)])
    assert doc is not None
    assert [item["id"] for item in doc["checks"]] == ["audit", "files"]


def test_evaluation_check_from_exec_result() -> None:
    result = SimpleNamespace(exit_code=0, stdout="ok\n", stderr="")
    row = evaluation_check("audit", status="PASS", exec_result=result, environment="audit")
    assert row["exit_code"] == 0
    assert row["stdout"] == "ok\n"
    assert row["stderr"] == ""
    assert row["environment"] == "audit"


def test_evaluation_check_decodes_bytes_and_drops_nan_score() -> None:
    result = SimpleNamespace(exit_code=0, stdout=b"ok\n", stderr=b"")
    row = evaluation_check("audit", score=float("nan"), exec_result=result)
    assert row["stdout"] == "ok\n"
    assert row["stderr"] == ""
    assert "score" not in row
