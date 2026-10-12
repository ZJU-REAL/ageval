"""ModelSpec resolve: nested model: and flat profile fields."""

from __future__ import annotations

from types import MappingProxyType
import pickle

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.config.profiles import load_job_document
from ageval.environments.protocol import WORKSPACE_PATH, Placement
from ageval.plugins.errors import ExtensionMaterializeError
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


def test_nested_and_flat_resolve_to_the_same_spec() -> None:
    nested = resolve_model(_NESTED, {})
    flat = resolve_model(
        "openai/glm-5.2",
        {
            "api": "responses",
            "reasoning_effort": "high",
            "timeout": 120,
            "watchdog": 300,
            "extra_body": {"reasoning": {"summary": "auto"}},
        },
    )
    assert nested == flat
    assert nested.id == "openai/glm-5.2"
    assert nested.api == "responses"
    assert nested.reasoning_effort == "high"
    assert nested.timeout == 120.0
    assert nested.watchdog == 300.0
    assert nested.extra["reasoning"] == {"summary": "auto"}


def test_flat_request_timeout_maps_to_timeout_and_zero_omits() -> None:
    mapped = resolve_model("openai/x", {"request_timeout": 90})
    assert mapped.timeout == 90.0
    omitted = resolve_model("openai/x", {"request_timeout": 0})
    assert omitted.timeout is None
    absent = resolve_model("openai/x", {})
    assert absent.timeout is None
    assert absent.api == "chat"
    assert absent.reasoning_effort is None
    assert absent.id == "openai/x"


def test_default_id_when_model_absent() -> None:
    spec = resolve_model(None, {})
    assert spec.id == "openai/gpt-4o-mini"


def test_api_short_names_and_compass_spellings() -> None:
    assert resolve_model("m", {"api": "CHAT"}).api == "chat"
    assert resolve_model("m", {"api": "Responses"}).api == "responses"
    with pytest.raises(ExtensionMaterializeError, match="miniswe_api_invalid"):
        resolve_model("m", {"api": "openai-chat"})
    with pytest.raises(ExtensionMaterializeError, match="miniswe_api_invalid"):
        resolve_model("m", {"api": "openai-responses"})


def test_nested_rejects_unknown_keys_and_non_effort_reasoning() -> None:
    with pytest.raises(ExtensionMaterializeError, match="miniswe_model_unknown:base_url"):
        resolve_model({"id": "m", "base_url": "http://x"}, {})
    with pytest.raises(ExtensionMaterializeError, match="miniswe_model_reasoning_unknown:summary"):
        resolve_model({"id": "m", "reasoning": {"summary": "auto"}}, {})


def test_extra_cannot_override_first_class_fields() -> None:
    with pytest.raises(ExtensionMaterializeError, match="extra_body_reserved"):
        resolve_model("m", {"extra_body": {"model": "other", "timeout": 1}})
    with pytest.raises(ExtensionMaterializeError, match="miniswe_extra_overrides:reasoning.effort"):
        resolve_model(
            {"id": "m", "extra": {"reasoning": {"effort": "low", "summary": "auto"}}},
            {},
        )


def test_nested_and_flat_together_conflict() -> None:
    with pytest.raises(ExtensionMaterializeError, match="miniswe_model_conflict:api"):
        resolve_model({"id": "m", "api": "chat"}, {"api": "responses"})
    with pytest.raises(ExtensionMaterializeError, match="request_timeout"):
        resolve_model("m", {"timeout": 10, "request_timeout": 10})


def test_watchdog_zero_and_unlimited_are_rejected() -> None:
    with pytest.raises(ExtensionMaterializeError, match="miniswe_watchdog_invalid"):
        resolve_model("m", {"watchdog": 0})
    with pytest.raises(ExtensionMaterializeError, match="miniswe_watchdog_invalid"):
        resolve_model("m", {"watchdog": "unlimited"})


def test_factory_uses_nested_spec_and_omits_unset_effort() -> None:
    spi = _executor(model=dict(_NESTED), options={"step_limit": 12})
    assert spi.spec == resolve_model(_NESTED, {})
    assert spi.model == "openai/glm-5.2"
    assert spi.api == "responses"
    assert spi.step_limit == 12
    assert spi.timeout == 120.0
    assert spi.watchdog == 300.0
    chat = _executor(model="openai/x")
    assert chat.spec.reasoning_effort is None
    assert chat.spec.watchdog is None
    assert chat.timeout is None
    assert chat.watchdog == 180.0
    body = chat._litellm_model_kwargs(key=None, base=None)
    assert "reasoning_effort" not in body
    assert "timeout" not in body
    assert "watchdog" not in body


def test_timeout_and_watchdog_are_independent() -> None:
    spi = _executor(model="openai/x", options={"timeout": 30, "watchdog": 90})
    assert spi.timeout == 30.0
    assert spi.watchdog == 90.0
    body = spi._litellm_model_kwargs(key=None, base=None)
    assert body["timeout"] == 30.0
    assert "watchdog" not in body
    assert "reasoning_effort" not in body


def test_explicit_zero_timeout_omits_http_clock_and_keeps_watchdog() -> None:
    spi = _executor(model="openai/x", options={"request_timeout": 0})
    assert spi.spec.timeout is None
    assert spi.timeout is None
    assert spi.watchdog == 180.0
    assert "timeout" not in spi._litellm_model_kwargs(key=None, base=None)


def test_http_timeout_seconds_omits_none_and_rejects_zero() -> None:
    from miniswe_plugin.llm_client import http_timeout_seconds

    assert http_timeout_seconds(None) is None
    assert http_timeout_seconds(30) == 30.0
    with pytest.raises(ValueError, match="miniswe_timeout_invalid"):
        http_timeout_seconds(0)


def test_client_timeout_none_does_not_become_180() -> None:
    pytest.importorskip("httpx")
    from miniswe_plugin.llm_client import client_timeout

    http_timeout, value = client_timeout(None)
    assert value is None
    assert http_timeout.connect is None
    assert http_timeout.read is None
    assert http_timeout.write is None
    assert http_timeout.pool is None
    _http, positive = client_timeout(30)
    assert positive == 30.0
    with pytest.raises(ValueError, match="miniswe_timeout_invalid"):
        client_timeout(0)


def test_responses_wire_maps_effort_and_keeps_extra_reasoning() -> None:
    spec = resolve_model(
        "openai/glm-5.2",
        {
            "api": "responses",
            "reasoning_effort": "high",
            "extra_body": {"reasoning": {"summary": "auto"}},
        },
    )
    body = wire_body(spec)
    assert body["reasoning"] == {"summary": "auto", "effort": "high"}
    assert "reasoning_effort" not in body


def test_responses_omits_unset_effort_and_keeps_summary() -> None:
    spec = resolve_model(
        "openai/x",
        {"api": "responses", "extra_body": {"reasoning": {"summary": "auto"}}},
    )
    body = wire_body(spec)
    assert body["reasoning"] == {"summary": "auto"}
    assert "reasoning_effort" not in body


def test_chat_wire_sends_effort_only_when_set() -> None:
    sent = wire_body(resolve_model("m", {"reasoning_effort": "low"}))
    assert sent["reasoning_effort"] == "low"
    assert "reasoning" not in sent
    omitted = wire_body(resolve_model("m", {"api": "chat"}))
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
    spi = _executor(model="openai/x", options={"reasoning_effort": "none"})
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
    assert spec.id == "openai/glm-5.2"
    assert spec.api == "responses"
    assert spec.reasoning_effort == "high"
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
