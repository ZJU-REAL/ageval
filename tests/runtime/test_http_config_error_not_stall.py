"""HTTP 4xx (except 408/429) is a model config error and never enters upstream stall."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ageval.model.errors import (
    FATAL_INVOKE_TITLE,
    FormatError,
    ModelConfigError,
    ProtocolError,
    TransportStall,
    fatal_invoke_failure,
    http_status_is_config_error,
    is_fatal_invoke_payload,
    is_recoverable_agent_invoke_error,
)
from ageval.runtime.parent_agent import _result_repeatable


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422, 499])
def test_4xx_is_config(code: int) -> None:
    assert http_status_is_config_error(code) is True


@pytest.mark.parametrize("code", [200, 302, 408, 429, 500, 502, 503, 504])
def test_408_429_and_non_4xx_are_not_config(code: int) -> None:
    assert http_status_is_config_error(code) is False


def test_parent_retries_only_a_transport_stall() -> None:
    stall = TransportStall("HTTPError:503", kind="http")
    assert _result_repeatable(SimpleNamespace(ok=False, failure=stall)) is True
    assert _result_repeatable(SimpleNamespace(ok=False, failure=stall, repeatable=False)) is False
    assert (
        _result_repeatable(
            SimpleNamespace(ok=False, failure=ModelConfigError("HTTPError:400"), repeatable=False)
        )
        is False
    )
    assert (
        _result_repeatable(SimpleNamespace(ok=False, failure=ProtocolError("bad", kind="bad_json")))
        is False
    )
    assert (
        _result_repeatable(SimpleNamespace(ok=False, failure=FormatError("bad actions"))) is False
    )
    assert _result_repeatable(SimpleNamespace(ok=False, error="HTTPError:503")) is False
    assert _result_repeatable(SimpleNamespace(ok=False, error="HTTPError:400")) is False
    assert _result_repeatable(SimpleNamespace(ok=False, error="URLError")) is False


def test_fatal_invoke_classification_is_narrow_and_stable() -> None:
    class StallExhausted(Exception):
        pass

    assert fatal_invoke_failure(failure=ModelConfigError("HTTPError:403")) == (
        "ModelConfigError",
        "ModelConfigError:HTTPError:403",
    )
    assert fatal_invoke_failure(
        error="stall_exhausted",
        failure=StallExhausted("TransportStall:TimeoutError:180"),
        metadata={"stall_exhausted": True},
    ) == ("StallExhausted", "StallExhausted:stall_exhausted")
    assert fatal_invoke_failure(failure=TransportStall("HTTPError:503")) == (
        "TransportStall",
        "TransportStall:HTTPError:503",
    )
    assert fatal_invoke_failure(failure=ProtocolError("bad_json")) is None
    assert fatal_invoke_failure(error="scripted_failure") is None

    completed = {"ok": False, "error": "ModelConfigError:HTTPError:403"}
    assert is_fatal_invoke_payload(completed) is True
    assert is_fatal_invoke_payload({"ok": True, "error": None}) is False
    error = {"phase": "run", "title": FATAL_INVOKE_TITLE, "message": "ModelConfigError:403"}
    assert is_recoverable_agent_invoke_error(error) is True
    assert is_recoverable_agent_invoke_error({**error, "phase": "evaluate"}) is False
    assert is_recoverable_agent_invoke_error({**error, "title": "task_run_failed"}) is False
