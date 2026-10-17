"""Core ModelSpec: nested model only, no gateway key list."""

from __future__ import annotations

from dataclasses import fields

import pytest

from ageval.model import (
    MODEL_SPEC_FIELDS,
    ModelConfigError,
    ModelSpec,
    require_model_support,
    resolve_model,
)
from ageval.plugins.errors import ExtensionRegistryError, PluginContractError
from ageval.runtime.upstream_stall import UpstreamStall

_NESTED = {
    "id": "openai/example-model",
    "api": "responses",
    "reasoning": {"effort": "xhigh"},
    "timeout": 120,
    "watchdog": 300,
    "extra": {"reasoning": {"summary": "auto"}, "temperature": 0},
}

_FIELDS = frozenset({"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"})


def test_nested_resolve_keeps_declared_values_and_opaque_extra() -> None:
    spec = resolve_model(_NESTED, {"step_limit": 12})
    assert spec == ModelSpec(
        id="openai/example-model",
        api="responses",
        reasoning_effort="xhigh",
        timeout=120.0,
        watchdog=300.0,
        extra={"reasoning": {"summary": "auto"}, "temperature": 0},
    )
    assert {item.name for item in fields(ModelSpec)} == MODEL_SPEC_FIELDS
    assert "extra_allowlist" not in MODEL_SPEC_FIELDS
    kept = resolve_model({"id": "m", "extra": {"drop_params": True, "temperature": 0.2}})
    assert kept.extra["drop_params"] is True
    assert kept.extra["temperature"] == 0.2


def test_omit_rules() -> None:
    spec = resolve_model({"id": "m"})
    assert spec.api == "chat"
    assert spec.reasoning_effort is None
    assert spec.timeout is None
    assert spec.watchdog is None
    assert spec.extra == {}
    with pytest.raises(ModelConfigError, match="model_timeout_invalid"):
        resolve_model({"id": "m", "timeout": 0})
    assert resolve_model({"id": "m", "reasoning": {"effort": "none"}}).reasoning_effort == "none"
    with pytest.raises(ModelConfigError, match="concrete tier"):
        resolve_model({"id": "m", "reasoning": {"effort": "max"}})
    assert resolve_model({"id": "m", "api": "CHAT"}).api == "chat"
    assert resolve_model({"id": "m", "api": "Responses"}).api == "responses"


def test_input_extra_mutation_does_not_change_the_spec() -> None:
    raw = {"id": "m", "extra": {"temperature": 0, "reasoning": {"summary": "auto"}}}
    spec = resolve_model(raw)
    raw["extra"]["temperature"] = 1
    raw["extra"]["reasoning"]["summary"] = "changed"
    assert spec.extra["temperature"] == 0
    assert spec.extra["reasoning"] == {"summary": "auto"}


def test_string_id_and_flat_keys_are_rejected() -> None:
    with pytest.raises(ModelConfigError, match="model_nested_required"):
        resolve_model("openai/example-model", {"api": "responses"})
    with pytest.raises(ModelConfigError, match="model_nested_required"):
        resolve_model(None, {})
    with pytest.raises(ModelConfigError, match="model_flat_rejected:api"):
        resolve_model({"id": "m", "api": "chat"}, {"api": "responses"})
    with pytest.raises(ModelConfigError, match="extra_body"):
        resolve_model({"id": "m"}, {"extra_body": {"temperature": 0}})
    with pytest.raises(ModelConfigError, match="extra_body"):
        resolve_model({"id": "m"}, {"extra_body": {}})
    with pytest.raises(ModelConfigError, match="request_timeout"):
        resolve_model({"id": "m"}, {"timeout": 10, "request_timeout": 10})


def test_unknown_and_invalid_fields() -> None:
    with pytest.raises(ModelConfigError, match="model_unknown:base_url"):
        resolve_model({"id": "m", "base_url": "http://x"})
    with pytest.raises(ModelConfigError, match="model_id_invalid"):
        resolve_model({"api": "chat"})
    with pytest.raises(ModelConfigError, match="model_api_invalid"):
        resolve_model({"id": "m", "api": "openai-chat"})
    with pytest.raises(ModelConfigError, match="model_reasoning_unknown:summary"):
        resolve_model({"id": "m", "reasoning": {"summary": "auto"}})
    with pytest.raises(ModelConfigError, match="model_timeout_invalid"):
        resolve_model({"id": "m", "timeout": -1})
    with pytest.raises(ModelConfigError, match="model_timeout_invalid"):
        resolve_model({"id": "m", "timeout": True})
    with pytest.raises(ModelConfigError, match="model_watchdog_invalid"):
        resolve_model({"id": "m", "watchdog": 0})
    with pytest.raises(ModelConfigError, match="model_watchdog_invalid"):
        resolve_model({"id": "m", "watchdog": "unlimited"})


def test_extra_cannot_replace_first_class_fields() -> None:
    with pytest.raises(ModelConfigError, match="model_extra_reserved:id,timeout"):
        resolve_model({"id": "m", "extra": {"id": "other", "timeout": 1, "temperature": 0}})
    with pytest.raises(ModelConfigError, match="model_extra_overrides:reasoning.effort"):
        resolve_model({"id": "m", "extra": {"reasoning": {"effort": "low", "summary": "auto"}}})


def test_require_model_support_rejects_api_fields_and_extra_keys() -> None:
    spec = resolve_model(_NESTED)
    with pytest.raises(ModelConfigError, match="model_api_unsupported:responses"):
        require_model_support(
            spec,
            supported_apis=frozenset({"chat"}),
            supported_model_fields=_FIELDS,
            extra_allowlist=frozenset({"temperature", "reasoning"}),
        )
    chat = resolve_model({"id": "m", "timeout": 30, "extra": {"temperature": 0}})
    with pytest.raises(ModelConfigError, match="model_field_unsupported:timeout"):
        require_model_support(
            chat,
            supported_apis=frozenset({"chat"}),
            supported_model_fields=frozenset({"id", "api", "extra"}),
            extra_allowlist=frozenset({"temperature"}),
        )
    with pytest.raises(ModelConfigError, match="model_extra_rejected:temperature"):
        require_model_support(
            chat,
            supported_apis=frozenset({"chat"}),
            supported_model_fields=_FIELDS,
            extra_allowlist=frozenset(),
        )
    require_model_support(
        resolve_model({"id": "m"}),
        supported_apis=frozenset({"chat"}),
        supported_model_fields=frozenset({"id", "api"}),
        extra_allowlist=frozenset(),
    )


def test_model_config_error_is_not_a_registry_or_stall_error() -> None:
    err = ModelConfigError("model_api_unsupported:chat")
    assert err.kind == "model_config"
    assert err.message == "model_api_unsupported:chat"
    assert not isinstance(err, ExtensionRegistryError)
    assert not isinstance(err, PluginContractError)
    assert not isinstance(err, UpstreamStall)
    contract = PluginContractError("extra_allowlist is not declared")
    assert contract.kind == "plugin_contract"
    assert isinstance(contract, ExtensionRegistryError)
    assert not isinstance(contract, ModelConfigError)
