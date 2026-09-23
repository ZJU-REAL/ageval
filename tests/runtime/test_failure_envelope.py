"""Worker envelopes keep a ScriptError title and do not unwrap a task group."""

from __future__ import annotations

from ageval.runtime.task_worker import failure_envelope
from ageval_sdk import ScriptError


def test_script_error_title_is_the_envelope_error() -> None:
    fields = failure_envelope(
        ScriptError(title="Workspace seed missing", message="seed.txt is not a file")
    )
    assert fields == {
        "error": "Workspace seed missing",
        "message": "seed.txt is not a file",
    }


def test_bare_exception_uses_the_class_name() -> None:
    fields = failure_envelope(ValueError("seed.txt is not a file"))
    assert fields == {"error": "ValueError", "message": "seed.txt is not a file"}


def test_exception_group_is_not_unwrapped() -> None:
    group = ExceptionGroup(
        "task",
        [ScriptError(title="Workspace seed missing", message="seed.txt is not a file")],
    )
    fields = failure_envelope(group)
    assert fields["error"] == "ExceptionGroup"
    assert fields["message"] == str(group)
