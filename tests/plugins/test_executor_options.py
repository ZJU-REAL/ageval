"""Frozen executor Options: unknown keys fail lock and name the field."""

from __future__ import annotations

import pytest
from tests.helpers.lock import CONFIG_MIN, job_document, lock_task

from ageval.config.errors import ConfigError
from ageval.plugins.contrib.acp.options import AcpOptions
from ageval.plugins.contrib.openai_http.options import OpenAIHTTPOptions


def test_unknown_option_names_the_nearest_field() -> None:
    with pytest.raises(ConfigError, match="idle_timeout_secnds") as raised:
        AcpOptions.parse({"entry": "pi", "idle_timeout_secnds": 30})
    assert "idle_timeout_seconds" in str(raised.value)


def test_openai_http_rejects_an_unknown_option() -> None:
    with pytest.raises(ConfigError, match="unknown option 'temperature'"):
        OpenAIHTTPOptions.parse({"temperature": 0})


def test_typo_profile_fails_lock_and_names_the_field() -> None:
    job = job_document(
        {
            "solver": {
                "executor": "acp",
                "model": {"id": "entry-default"},
                "options": {"entry": "pi", "idle_timeout_secnds": 30},
                "extensions": [{"plugin": "acp"}, {"plugin": "local"}],
            }
        }
    )
    with pytest.raises(ConfigError, match="idle_timeout_secnds") as raised:
        lock_task(CONFIG_MIN, "minimal", job=job)
    assert "did you mean 'idle_timeout_seconds'" in str(raised.value)
