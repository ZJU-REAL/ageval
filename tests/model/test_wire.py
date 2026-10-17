"""One chat body and one responses body. Effort and timeout are omitted when unset."""

from __future__ import annotations

import pytest

from ageval.model import ModelConfigError, ModelSpec, resolve_model
from ageval.model.wire import chat_body, responses_body


def _spec(api: str, effort: str | None) -> ModelSpec:
    raw: dict[str, object] = {"id": "m", "api": api}
    if effort is not None:
        raw["reasoning"] = {"effort": effort}
    return resolve_model(raw)


@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize("effort", ["high", None])
def test_wire_covers_chat_and_responses_with_effort_present_or_absent(
    api: str, effort: str | None
) -> None:
    spec = _spec(api, effort)
    if api == "chat":
        body = chat_body(spec)
        assert "reasoning" not in body
        if effort is None:
            assert "reasoning_effort" not in body
        else:
            assert body["reasoning_effort"] == effort
    else:
        body = responses_body(spec)
        assert "reasoning_effort" not in body
        if effort is None:
            assert "reasoning" not in body
        else:
            assert body["reasoning"] == {"effort": effort}


def test_effort_none_is_sent() -> None:
    spec = _spec("chat", "none")
    assert chat_body(spec)["reasoning_effort"] == "none"
    responses = resolve_model({"id": "m", "api": "responses", "reasoning": {"effort": "none"}})
    assert responses_body(responses)["reasoning"] == {"effort": "none"}


def test_timeout_is_included_only_when_set() -> None:
    spec = resolve_model({"id": "m", "timeout": 30, "api": "responses"})
    assert chat_body(spec)["timeout"] == 30.0
    assert responses_body(spec)["timeout"] == 30.0
    omitted = resolve_model({"id": "m"})
    assert "timeout" not in chat_body(omitted)
    assert "timeout" not in responses_body(omitted)


def test_responses_merges_extra_reasoning_and_effort_wins() -> None:
    spec = resolve_model(
        {
            "id": "m",
            "api": "responses",
            "reasoning": {"effort": "high"},
            "extra": {"reasoning": {"summary": "auto"}, "temperature": 0},
        }
    )
    body = responses_body(spec)
    assert body["reasoning"] == {"summary": "auto", "effort": "high"}
    assert body["temperature"] == 0


def test_responses_rejects_a_non_mapping_reasoning_extra() -> None:
    spec = ModelSpec(
        id="m",
        api="responses",
        reasoning_effort="high",
        timeout=None,
        watchdog=None,
        extra={"reasoning": "nope"},
    )
    with pytest.raises(ModelConfigError, match="model_reasoning_invalid"):
        responses_body(spec)
