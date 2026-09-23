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
        assert result.error_phase is None


def test_bind_result_rejects_lowercase_and_unknown() -> None:
    for status in ("pass", "PASSED", "ok", "ERROR", "", None):
        raw = {"status": status} if status is not None else {}
        result = bind_result(
            evaluator_raw=raw,
            kind="local",
            evidence_path="/tmp/evidence",
        )
        assert result.status == "ERROR"
        assert result.error_phase == "evaluate"


def test_bind_result_missing_raw_is_error() -> None:
    result = bind_result(
        evaluator_raw=None,
        kind="local",
        evidence_path="/tmp/evidence",
    )
    assert result.status == "ERROR"
    assert result.error_phase == "evaluate"


def test_bind_result_phase_failure_wins() -> None:
    result = bind_result(
        evaluator_raw={"status": "PASS", "score": 1},
        kind="local",
        evidence_path="/tmp/evidence",
        error_phase="run",
    )
    assert result.status == "ERROR"
    assert result.error_phase == "run"
    assert result.score is None


def test_bind_result_timeout_text_stays_a_phase_error() -> None:
    run_hit = bind_result(
        evaluator_raw={"status": "PASS", "score": 1},
        kind="local",
        evidence_path="/tmp/evidence",
        error_phase="run",
    )
    assert run_hit.status == "ERROR"
    assert run_hit.score is None
    assert run_hit.error_phase == "run"
    assert run_hit.metrics == {}

    evaluate_hit = bind_result(
        evaluator_raw=None,
        kind="docker",
        evidence_path="/tmp/evidence",
        error_phase="evaluate",
    )
    assert evaluate_hit.status == "ERROR"
    assert evaluate_hit.score is None
    assert evaluate_hit.error_phase == "evaluate"
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
        error_phase="environment",
    )
    assert result.status == "ERROR"
    assert result.error_phase == "environment"
    assert result.score is None
