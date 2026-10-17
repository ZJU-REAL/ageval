"""ModelSpec resolve: nested model only."""

from __future__ import annotations

import pickle
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.config.profiles import load_job_document
from ageval.environments.protocol import WORKSPACE_PATH, Placement
from ageval.plugins.protocol import intent_from_profile
from ageval.runtime.agent_binding import executor_model_argument, executor_model_id

ROOT = Path(__file__).resolve().parents[2]
_SRC = ROOT / "plugins" / "miniswe" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from miniswe_plugin.factory import build_executor  # noqa: E402
from miniswe_plugin.model import ModelConfigError, ModelSpec, resolve_model, wire_body  # noqa: E402

_NESTED = {
    "id": "openai/glm-5.2",
    "api": "responses",
    "reasoning": {"effort": "high"},
    "timeout": 120,
    "watchdog": 300,
    "extra": {"reasoning": {"summary": "auto"}},
}


def _placement() -> Placement:
    return Placement(target_id="box", user="10001:10001", workdir=WORKSPACE_PATH)


def _executor(**kwargs: object):
    return build_executor(
        host=SimpleNamespace(kind="local"),
        placement=_placement(),
        **kwargs,  # type: ignore[arg-type]
    )


def test_nested_spec_keeps_effort_timeout_and_extra() -> None:
    nested = resolve_model(_NESTED, {})
    assert nested.id == "openai/glm-5.2"
    assert nested.api == "responses"
    assert nested.reasoning_effort == "high"
    assert nested.timeout == 120.0
    assert nested.watchdog == 300.0
    assert nested.extra["reasoning"] == {"summary": "auto"}


def test_flat_model_and_option_keys_are_rejected() -> None:
    with pytest.raises(ModelConfigError, match="model_nested_required"):
        resolve_model("openai/x", {})
    with pytest.raises(ModelConfigError, match="model_flat_rejected"):
        resolve_model({"id": "m"}, {"extra_body": {"temperature": 0}})
    with pytest.raises(ModelConfigError, match="request_timeout"):
        resolve_model({"id": "m"}, {"request_timeout": 90})
    with pytest.raises(ModelConfigError, match="model_flat_rejected"):
        resolve_model({"id": "m", "api": "chat"}, {"api": "responses"})


def test_default_id_when_model_absent() -> None:
    spi = _executor()
    assert spi.model == "openai/gpt-4o-mini"
    assert spi.spec.api == "chat"
    assert spi.spec.reasoning_effort is None
    assert spi.watchdog == 180.0


def test_api_short_names() -> None:
    assert resolve_model({"id": "m", "api": "CHAT"}).api == "chat"
    assert resolve_model({"id": "m", "api": "Responses"}).api == "responses"
    with pytest.raises(ModelConfigError, match="model_api_invalid"):
        resolve_model({"id": "m", "api": "openai-chat"})
    with pytest.raises(ModelConfigError, match="model_api_invalid"):
        resolve_model({"id": "m", "api": "openai-responses"})


def test_nested_rejects_unknown_keys_and_non_effort_reasoning() -> None:
    with pytest.raises(ModelConfigError, match="model_unknown:base_url"):
        resolve_model({"id": "m", "base_url": "http://x"}, {})
    with pytest.raises(ModelConfigError, match="model_reasoning_unknown:summary"):
        resolve_model({"id": "m", "reasoning": {"summary": "auto"}}, {})


def test_extra_cannot_override_first_class_fields() -> None:
    with pytest.raises(ModelConfigError, match="model_extra_reserved"):
        resolve_model({"id": "m", "extra": {"timeout": 1}}, {})
    with pytest.raises(ModelConfigError, match="model_extra_overrides:reasoning.effort"):
        resolve_model(
            {"id": "m", "extra": {"reasoning": {"effort": "low", "summary": "auto"}}},
            {},
        )


def test_watchdog_zero_and_unlimited_are_rejected() -> None:
    with pytest.raises(ModelConfigError, match="model_watchdog_invalid"):
        resolve_model({"id": "m", "watchdog": 0}, {})
    with pytest.raises(ModelConfigError, match="model_watchdog_invalid"):
        resolve_model({"id": "m", "watchdog": "unlimited"}, {})


def test_factory_uses_nested_spec_and_omits_unset_effort() -> None:
    spi = _executor(model=dict(_NESTED), options={"step_limit": 12})
    assert spi.spec == resolve_model(_NESTED, {})
    assert spi.model == "openai/glm-5.2"
    assert spi.api == "responses"
    assert spi.step_limit == 12
    assert spi.timeout == 120.0
    assert spi.watchdog == 300.0
    chat = _executor(model={"id": "openai/x"})
    assert chat.spec.reasoning_effort is None
    assert chat.spec.watchdog is None
    assert chat.spec.timeout is None
    assert chat.timeout == 180.0
    assert chat.watchdog == 180.0
    body = chat._litellm_model_kwargs(key=None, base=None)
    assert "reasoning_effort" not in body
    assert "timeout" not in body
    assert "watchdog" not in body


def test_timeout_and_watchdog_are_independent() -> None:
    spi = _executor(model={"id": "openai/x", "timeout": 30, "watchdog": 90})
    assert spi.timeout == 30.0
    assert spi.watchdog == 90.0
    body = spi._litellm_model_kwargs(key=None, base=None)
    assert body["timeout"] == 30.0
    assert "watchdog" not in body
    assert "reasoning_effort" not in body


def test_explicit_zero_timeout_is_rejected() -> None:
    with pytest.raises(ModelConfigError, match="model_timeout_invalid"):
        _executor(model={"id": "openai/x", "timeout": 0})


def test_http_timeout_seconds_uses_the_table_default_and_rejects_zero() -> None:
    from miniswe_plugin.llm_client import http_timeout_seconds

    assert http_timeout_seconds(None) == 180.0
    assert http_timeout_seconds(30) == 30.0
    with pytest.raises(ValueError, match="miniswe_timeout_invalid"):
        http_timeout_seconds(0)


def test_client_timeout_omit_uses_the_table_default() -> None:
    pytest.importorskip("httpx")
    from miniswe_plugin.llm_client import client_timeout

    http_timeout, value = client_timeout(None)
    assert value == 180.0
    assert http_timeout.connect == 30.0
    assert http_timeout.read == 180.0
    _http, positive = client_timeout(30)
    assert positive == 30.0
    with pytest.raises(ValueError, match="miniswe_timeout_invalid"):
        client_timeout(0)


def test_responses_wire_maps_effort_and_keeps_extra_reasoning() -> None:
    spec = resolve_model(
        {
            "id": "dashscope/glm-5.2",
            "api": "responses",
            "reasoning": {"effort": "high"},
            "extra": {"reasoning": {"summary": "auto"}},
        },
        {},
    )
    body = wire_body(spec)
    assert body["reasoning"] == {"summary": "auto", "effort": "high"}
    assert "reasoning_effort" not in body


def test_responses_omits_unset_effort_and_keeps_summary() -> None:
    spec = resolve_model(
        {"id": "openai/x", "api": "responses", "extra": {"reasoning": {"summary": "auto"}}},
        {},
    )
    body = wire_body(spec)
    assert body["reasoning"] == {"summary": "auto"}
    assert "reasoning_effort" not in body


def test_chat_wire_sends_effort_only_when_set() -> None:
    sent = wire_body(resolve_model({"id": "m", "reasoning": {"effort": "low"}}, {}))
    assert sent["reasoning_effort"] == "low"
    assert "reasoning" not in sent
    omitted = wire_body(resolve_model({"id": "m", "api": "chat"}, {}))
    assert "reasoning_effort" not in omitted


def test_unmapped_api_fails_before_a_request() -> None:
    spec = ModelSpec(
        id="m",
        api="openai-responses",
        reasoning_effort="high",
        timeout=None,
        watchdog=None,
        extra={},
    )
    with pytest.raises(ModelConfigError, match="miniswe_api_invalid"):
        wire_body(spec)


def test_config_http_status_is_terminal() -> None:
    from miniswe_plugin.llm_client import raise_for_http_status

    for status in (400, 401, 403, 404, 422):
        with pytest.raises(ModelConfigError, match=f"chat_http_{status}"):
            raise_for_http_status("chat_http", status, "bad schema")
    for status in (408, 429, 500, 503):
        with pytest.raises(RuntimeError, match=f"responses_http_{status}"):
            raise_for_http_status("responses_http", status, "later")


def test_declared_effort_none_is_sent() -> None:
    spi = _executor(model={"id": "openai/x", "reasoning": {"effort": "none"}})
    assert spi.spec.reasoning_effort == "none"
    assert spi._litellm_model_kwargs(key=None, base=None)["reasoning_effort"] == "none"


def test_example_profile_resolves() -> None:
    doc = load_job_document(ROOT / "examples/agents/miniswe-default/profiles.model.yaml")
    row = doc.profiles["solver"]
    options: dict[str, object] = {}
    for item in row["extensions"]:
        if item.get("plugin") == "miniswe":
            options = dict(item.get("options") or {})
    spec = resolve_model(row["model"], options)
    assert spec.id == "dashscope/glm-5.2"
    assert spec.api == "responses"
    assert spec.reasoning_effort == "xhigh"
    assert spec.timeout == 120.0
    assert spec.watchdog == 300.0
    assert spec.extra["reasoning"] == {"summary": "auto"}


def test_frozen_nested_model_argument_is_pickleable() -> None:
    """Lock freezes nested model; factory argument must thaw before pickle."""
    from ageval.config.model import freeze
    from ageval.config.profiles import model_argument

    frozen = freeze(_NESTED)
    argument = model_argument(frozen)
    assert isinstance(argument, dict)
    assert argument["id"] == "openai/glm-5.2"
    assert argument["reasoning"]["effort"] == "high"
    pickle.dumps(argument)


def test_profile_model_reaches_intent_and_executor_argument() -> None:
    intent = intent_from_profile({"id": "solver", "executor": "miniswe", "model": dict(_NESTED)})
    assert intent.model == _NESTED
    argument = executor_model_argument(_NESTED)
    assert isinstance(argument, dict)
    assert argument["id"] == "openai/glm-5.2"
    assert executor_model_id(_NESTED) == "openai/glm-5.2"
    assert executor_model_argument(None) == "entry-default"
    assert executor_model_argument(" openai/x ") == "openai/x"
    assert executor_model_id(None) == "entry-default"
