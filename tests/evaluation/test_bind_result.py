"""Verdict bind is fail-closed on unknown status strings."""

from ageval.evaluation.bind import bind_result


def test_bind_result_records_the_run_limit() -> None:
    result = bind_result(
        evaluator_raw={"status": "FAIL", "score": 0.3, "metrics": {"tests_passed": 3}},
        kind="local",
        evidence_path="/tmp/evidence",
        limit="wall_time_seconds",
    )
    assert result.status == "FAIL"
    assert result.score == 0.3
    assert result.limit == "wall_time_seconds"
    assert result.as_dict()["limit"] == "wall_time_seconds"
    assert result.as_dict()["error"] is None
    assert result.metrics == {"tests_passed": 3}


def test_bind_result_accepts_pass_and_fail() -> None:
    for status in ("PASS", "FAIL"):
        result = bind_result(
            evaluator_raw={"status": status, "score": 1},
            kind="local",
            evidence_path="/tmp/evidence",
        )
        assert result.status == status
        assert result.error is None
        assert result.as_dict()["error"] is None


def test_bind_result_rejects_lowercase_and_unknown() -> None:
    for status in ("pass", "PASSED", "ok", "ERROR", "", None):
        raw = {"status": status} if status is not None else {}
        result = bind_result(
            evaluator_raw=raw,
            kind="local",
            evidence_path="/tmp/evidence",
        )
        assert result.status == "ERROR"
        assert result.as_dict()["error"] == {
            "phase": "evaluate",
            "title": "evaluator_invalid_status",
            "message": "evaluator_invalid_status",
        }


def test_bind_result_missing_raw_is_error() -> None:
    result = bind_result(
        evaluator_raw=None,
        kind="local",
        evidence_path="/tmp/evidence",
    )
    assert result.status == "ERROR"
    assert result.as_dict()["error"] == {
        "phase": "evaluate",
        "title": "evaluator_invalid_status",
        "message": "evaluator produced no verdict document",
    }


def test_bind_result_phase_failure_wins() -> None:
    error = {"phase": "run", "title": "ValueError", "message": "seed.txt is not a file"}
    result = bind_result(
        evaluator_raw={"status": "PASS", "score": 1},
        kind="local",
        evidence_path="/tmp/evidence",
        error=error,
    )
    assert result.status == "ERROR"
    assert result.as_dict()["error"] == error
    assert result.score is None


def test_bind_result_timeout_text_stays_a_phase_error() -> None:
    run_hit = bind_result(
        evaluator_raw={"status": "PASS", "score": 1},
        kind="local",
        evidence_path="/tmp/evidence",
        error={"phase": "run", "title": "ValueError", "message": "timed out"},
    )
    assert run_hit.status == "ERROR"
    assert run_hit.score is None
    assert run_hit.as_dict()["error"]["phase"] == "run"
    assert run_hit.metrics == {}

    evaluate_hit = bind_result(
        evaluator_raw=None,
        kind="docker",
        evidence_path="/tmp/evidence",
        error={
            "phase": "evaluate",
            "title": "evaluate_timeout",
            "message": "evaluate_timeout",
        },
    )
    assert evaluate_hit.status == "ERROR"
    assert evaluate_hit.score is None
    assert evaluate_hit.as_dict()["error"]["title"] == "evaluate_timeout"
    assert evaluate_hit.metrics == {}


def test_bind_result_ignores_checks_key() -> None:
    result = bind_result(
        evaluator_raw={
            "status": "PASS",
            "score": 1,
            "metrics": {"n": 1},
            "checks": [{"id": "audit", "status": "FAIL"}],
        },
        kind="local",
        evidence_path="/tmp/evidence",
    )
    assert result.status == "PASS"
    assert result.score == 1.0
    assert result.metrics == {"n": 1}


def test_bind_result_environment_timeout_stays_error() -> None:
    result = bind_result(
        evaluator_raw=None,
        kind="docker",
        evidence_path="/tmp/evidence",
        error={
            "phase": "environment",
            "title": "environment_timeout",
            "message": "environment_timeout",
        },
    )
    assert result.status == "ERROR"
    assert result.as_dict()["error"]["phase"] == "environment"
    assert result.as_dict()["error"]["title"] == "environment_timeout"
    assert result.score is None
