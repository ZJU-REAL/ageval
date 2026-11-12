"""A sealed fatal-invoke ERROR resumes in the same Attempt and slot."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.application.run import _locate_resume
from ageval.application.suite.suite_run import (
    _error_attempt_keys,
    _existing_attempt_keys,
    _recoverable_invoke_keys,
)
from ageval.attempt.recover import find_recoverable_invoke_attempt, write_attempt_header
from ageval.evidence.activity import ActivityLog
from ageval.model.errors import FATAL_INVOKE_TITLE

_DIGEST = "digest-a"
_SUITE = "suite-1"


def _seal(
    root: Path,
    *,
    attempt: str,
    digest: str = _DIGEST,
    title: str = FATAL_INVOKE_TITLE,
    phase: str | None = "run",
    status: str = "ERROR",
    with_activity: bool = True,
) -> Path:
    attempt_dir = root / ".ageval" / "runs" / attempt
    if with_activity:
        log = ActivityLog.open(attempt_dir / "activity.jsonl")
        write_attempt_header(
            log,
            run_id=attempt,
            trial_id=attempt,
            attempt_id=attempt,
            task_id="alpha",
            attempt_index=0,
            suite_run_id=_SUITE,
            digest=digest,
            environment_kind="local",
            nonce="nce_test",
        )
    else:
        attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "result.json").write_text(
        json.dumps(
            {
                "status": status,
                "limit": None,
                "error": {
                    "phase": phase,
                    "title": title,
                    "message": "ModelConfigError:chat_http_403:insufficient balance",
                },
            }
        ),
        encoding="utf-8",
    )
    return attempt_dir


def test_explicit_resume_attaches_to_the_sealed_fatal_invoke(tmp_path: Path) -> None:
    sealed = _seal(tmp_path, attempt="att_model")
    plan = _locate_resume(
        tmp_path,
        lock_digest=_DIGEST,
        task_id="alpha",
        attempt_index=0,
        resume_attempt_id=sealed.name,
        suite_run_id=None,
        recover_unsealed=False,
    )
    assert plan.refused is None
    assert plan.attempt_id == "att_model"
    assert plan.activity is not None


def test_suite_lookup_requires_matching_slot_and_digest(tmp_path: Path) -> None:
    sealed = _seal(tmp_path, attempt="att_model")
    found = find_recoverable_invoke_attempt(
        tmp_path,
        suite_run_id=_SUITE,
        task_id="alpha",
        attempt_index=0,
        digest=_DIGEST,
    )
    assert found == sealed
    assert (
        find_recoverable_invoke_attempt(
            tmp_path,
            suite_run_id=_SUITE,
            task_id="alpha",
            attempt_index=0,
            digest="other",
        )
        is None
    )
    plan = _locate_resume(
        tmp_path,
        lock_digest=_DIGEST,
        task_id="alpha",
        attempt_index=0,
        resume_attempt_id=None,
        suite_run_id=_SUITE,
        recover_unsealed=True,
        resume_recorded_invoke_error=True,
    )
    assert plan.attempt_id == "att_model"


def test_other_errors_and_ordinary_settled_results_stay_refused(tmp_path: Path) -> None:
    env = _seal(
        tmp_path,
        attempt="att_env",
        phase="environment",
        title="environment_timeout",
    )
    fail = _seal(tmp_path, attempt="att_fail", status="FAIL", title="", phase=None)
    for path in (env, fail):
        plan = _locate_resume(
            tmp_path,
            lock_digest=_DIGEST,
            task_id="alpha",
            attempt_index=0,
            resume_attempt_id=path.name,
            suite_run_id=None,
            recover_unsealed=False,
        )
        assert plan.refused is not None
        assert plan.refused[1].error == {
            "phase": "run",
            "title": "attempt_already_settled",
            "message": "result.json already exists",
        }


def test_missing_recovery_activity_does_not_attach(tmp_path: Path) -> None:
    _seal(tmp_path, attempt="att_bare", with_activity=False)
    assert (
        find_recoverable_invoke_attempt(
            tmp_path,
            suite_run_id=_SUITE,
            task_id="alpha",
            attempt_index=0,
            digest=_DIGEST,
        )
        is None
    )
    plan = _locate_resume(
        tmp_path,
        lock_digest=_DIGEST,
        task_id="alpha",
        attempt_index=0,
        resume_attempt_id="att_bare",
        suite_run_id=None,
        recover_unsealed=False,
    )
    assert plan.refused is not None
    assert plan.refused[1].error is not None
    assert plan.refused[1].error["title"] == "activity_log_missing"


def test_unsealed_attempt_wins_over_a_recoverable_error(tmp_path: Path) -> None:
    _seal(tmp_path, attempt="att_sealed")
    unsealed = tmp_path / ".ageval" / "runs" / "att_open"
    log = ActivityLog.open(unsealed / "activity.jsonl")
    write_attempt_header(
        log,
        run_id="att_open",
        trial_id="att_open",
        attempt_id="att_open",
        task_id="alpha",
        attempt_index=0,
        suite_run_id=_SUITE,
        digest=_DIGEST,
        environment_kind="local",
        nonce="nce_open",
    )
    plan = _locate_resume(
        tmp_path,
        lock_digest=_DIGEST,
        task_id="alpha",
        attempt_index=0,
        resume_attempt_id=None,
        suite_run_id=_SUITE,
        recover_unsealed=True,
        resume_recorded_invoke_error=True,
    )
    assert plan.attempt_id == "att_open"


def test_suite_scheduler_attaches_fatal_error_but_not_other_errors() -> None:
    fatal = {
        "task_id": "alpha",
        "attempt_index": 0,
        "status": "ERROR",
        "error": {
            "phase": "run",
            "title": FATAL_INVOKE_TITLE,
            "message": "TransportStall:HTTPError:503",
        },
    }
    rows = [
        fatal,
        {
            "task_id": "beta",
            "attempt_index": 0,
            "status": "ERROR",
            "error": {
                "phase": "environment",
                "title": "environment_timeout",
                "message": "environment_timeout",
            },
        },
        {"task_id": "gamma", "attempt_index": 0, "status": "FAIL", "error": None},
    ]
    attach = _recoverable_invoke_keys(rows)
    assert attach == {("alpha", 0)}
    assert _error_attempt_keys(rows) == {("beta", 0)}
    assert _existing_attempt_keys(rows) - attach == {("beta", 0), ("gamma", 0)}
