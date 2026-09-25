"""ScriptError keeps a stable title and this occurrence's message."""

from __future__ import annotations

import pytest

from ageval_sdk import ScriptError


def test_script_error_keeps_title_and_message() -> None:
    exc = ScriptError(title="Workspace seed missing", message="seed.txt is not a file")
    assert exc.title == "Workspace seed missing"
    assert exc.message == "seed.txt is not a file"
    assert str(exc) == "seed.txt is not a file"


def test_script_error_rejects_a_blank_title() -> None:
    with pytest.raises(ValueError, match="title"):
        ScriptError(title="  ", message="detail")


def test_script_error_rejects_a_non_string_message() -> None:
    with pytest.raises(TypeError, match="message"):
        ScriptError(title="Judge response empty", message=None)  # type: ignore[arg-type]
