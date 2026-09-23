"""Parent exceptions become the same error object the result stores."""

from __future__ import annotations

from ageval.config.errors import ConfigError
from ageval.environments.protocol import EnvironmentFailure
from ageval.evaluation.error_record import (
    RecordedError,
    error_record_from_exception,
    message_from_envelope,
)


def test_recorded_error_keeps_the_split_fields() -> None:
    record = error_record_from_exception(
        RecordedError("Workspace seed missing", "seed.txt is not a file"),
        phase="run",
    )
    assert record == {
        "phase": "run",
        "title": "Workspace seed missing",
        "message": "seed.txt is not a file",
    }


def test_environment_failure_uses_its_kind() -> None:
    exc = EnvironmentFailure("environment_setup_failed", "environment/setup.sh exited 1: missing")
    record = error_record_from_exception(exc, phase="environment")
    assert record["title"] == "environment_setup_failed"
    assert record["message"] == "environment/setup.sh exited 1: missing"
    assert record["phase"] == "environment"


def test_config_error_title_is_the_class_name() -> None:
    exc = ConfigError("invalid_package", "broken", location="ageval.yaml")
    record = error_record_from_exception(exc, phase=None)
    assert record["phase"] is None
    assert record["title"] == "ConfigError"
    assert record["message"] == str(exc)


def test_engine_token_is_the_title() -> None:
    record = error_record_from_exception(TimeoutError("evaluate_timeout"), phase="evaluate")
    assert record == {
        "phase": "evaluate",
        "title": "evaluate_timeout",
        "message": "evaluate_timeout",
    }


def test_other_exceptions_use_the_class_name() -> None:
    record = error_record_from_exception(ValueError("seed.txt is not a file"), phase="run")
    assert record == {
        "phase": "run",
        "title": "ValueError",
        "message": "seed.txt is not a file",
    }


def test_envelope_message_falls_back_to_the_stderr_tail() -> None:
    assert message_from_envelope({"stderr": "x" * 600}) == "x" * 500
    assert message_from_envelope({"message": "seed.txt is not a file", "stderr": "noise"}) == (
        "seed.txt is not a file"
    )
