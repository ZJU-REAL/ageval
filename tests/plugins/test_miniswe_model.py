"""ModelSpec resolve: nested model: and flat profile fields."""

from __future__ import annotations

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
from miniswe_plugin.model import resolve_model  # noqa: E402

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


def test_factory_uses_nested_spec_and_keeps_chat_none_dark_default() -> None:
    spi = _executor(model=dict(_NESTED), options={"step_limit": 12})
    assert spi.spec == resolve_model(_NESTED, {})
    assert spi.model == "openai/glm-5.2"
    assert spi.api == "responses"
    assert spi.step_limit == 12
    assert spi.request_timeout == 120.0
    chat = _executor(model="openai/x")
    assert chat.spec.reasoning_effort is None
    assert chat._litellm_model_kwargs(key=None, base=None)["reasoning_effort"] == "none"
    assert chat.request_timeout == 180.0


def test_explicit_zero_timeout_stays_off_the_kwargs_but_spec_omits() -> None:
    spi = _executor(model="openai/x", options={"request_timeout": 0})
    assert spi.spec.timeout is None
    assert spi.request_timeout == 0.0
    assert "timeout" not in spi._litellm_model_kwargs(key=None, base=None)


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


def test_profile_model_reaches_intent_and_executor_argument() -> None:
    intent = intent_from_profile({"id": "solver", "executor": "miniswe", "model": dict(_NESTED)})
    assert intent.model == _NESTED
    assert executor_model_argument(_NESTED)["id"] == "openai/glm-5.2"
    assert executor_model_id(_NESTED) == "openai/glm-5.2"
    assert executor_model_argument(None) == "entry-default"
    assert executor_model_argument(" openai/x ") == "openai/x"
    assert executor_model_id(None) == "entry-default"
