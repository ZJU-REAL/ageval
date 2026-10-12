"""HTTP 4xx (except 408/429) is a model config error and never enters upstream stall."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ageval.model.errors import http_error_reason_is_config_error, http_status_is_config_error
from ageval.runtime.parent_agent import _result_repeatable


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422, 499])
def test_4xx_is_config(code: int) -> None:
    assert http_status_is_config_error(code) is True


@pytest.mark.parametrize("code", [200, 302, 408, 429, 500, 502, 503, 504])
def test_408_429_and_non_4xx_are_not_config(code: int) -> None:
    assert http_status_is_config_error(code) is False


@pytest.mark.parametrize(
    ("reason", "config"),
    [
        ("HTTPError:400", True),
        ("HTTPError:404", True),
        ("ModelConfigError:HTTPError:401", True),
        ("HTTPError:429", False),
        ("HTTPError:408", False),
        ("HTTPError:503", False),
        ("URLError", False),
        ("TimeoutError:openai_http_watchdog:180", False),
        ("", False),
    ],
)
def test_reason_classification(reason: str, config: bool) -> None:
    assert http_error_reason_is_config_error(reason) is config


def test_shared_stall_path_refuses_4xx_from_any_http_executor() -> None:
    # anthropic-http (or any executor) still reports a bare HTTPError:<code>.
    assert _result_repeatable(SimpleNamespace(ok=False, error="HTTPError:400")) is False
    assert _result_repeatable(SimpleNamespace(ok=False, error="HTTPError:429")) is True
    assert _result_repeatable(SimpleNamespace(ok=False, error="HTTPError:502")) is True
    assert _result_repeatable(SimpleNamespace(ok=False, error="URLError")) is True
    assert (
        _result_repeatable(SimpleNamespace(ok=False, error="URLError", repeatable=False)) is False
    )
