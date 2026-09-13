"""Verdict bind is fail-closed on unknown status strings."""

from ageval.evaluation.bind import bind_result


def test_bind_result_accepts_pass_fail_error() -> None:
    for status in ("PASS", "FAIL", "ERROR"):
        result = bind_result(
            evaluator_raw={"status": status, "score": 1},
            kind="local",
            evidence_path="/tmp/evidence",
        )
        assert result.status == status


def test_bind_result_rejects_lowercase_and_unknown() -> None:
    for status in ("pass", "PASSED", "ok", "", None):
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


def test_bind_result_run_timeout_is_fail() -> None:
    result = bind_result(
        evaluator_raw={"status": "PASS", "score": 1},
        kind="local",
        evidence_path="/tmp/evidence",
        error_phase="run",
        error_detail="RuntimeError: task_run_timeout",
    )
    assert result.status == "FAIL"
    assert result.score == 0.0
    assert result.error_phase is None
    assert result.metrics["reason"] == "timeout"
    assert result.metrics["timeout_phase"] == "run"


def test_bind_result_evaluate_timeout_is_fail() -> None:
    result = bind_result(
        evaluator_raw=None,
        kind="docker",
        evidence_path="/tmp/evidence",
        error_phase="evaluate",
        error_detail=(
            "RuntimeError: TimeoutExpired: Command '['docker', 'exec']' "
            "timed out after 1800 seconds"
        ),
    )
    assert result.status == "FAIL"
    assert result.score == 0.0
    assert result.error_phase is None
    assert result.metrics["timeout_phase"] == "evaluate"


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
        error_detail="TimeoutError: docker start timed out",
    )
    assert result.status == "ERROR"
    assert result.error_phase == "environment"
    assert result.score is None
