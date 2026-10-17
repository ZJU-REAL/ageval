"""Usage is a measurement or a reason. JSON null is not a usage."""

from __future__ import annotations

from ageval.model.usage import (
    LOST_ON_TIMEOUT,
    NOT_REPORTED,
    Usage,
    UsageUnavailable,
    adopt_usage,
    is_measured_usage,
    to_sealed_document,
)


def test_numbers_become_usage() -> None:
    usage = adopt_usage({"prompt_tokens": 4, "completion_tokens": 1, "cost_usd": 0.02})
    assert isinstance(usage, Usage)
    assert usage.to_sealed() == {
        "prompt_tokens": 4,
        "completion_tokens": 1,
        "cost_usd": 0.02,
    }
    assert usage["prompt_tokens"] == 4
    assert is_measured_usage(usage) is True
    assert bool(usage) is True


def test_empty_and_none_are_not_reported() -> None:
    assert adopt_usage(None) is NOT_REPORTED
    assert adopt_usage({}) is NOT_REPORTED
    assert adopt_usage({"prompt_tokens": None}) is NOT_REPORTED
    sealed = to_sealed_document(None)
    assert sealed == {"unavailable": "not_reported"}
    assert to_sealed_document(Usage()) == {"unavailable": "not_reported"}
    assert is_measured_usage(NOT_REPORTED) is False
    assert bool(NOT_REPORTED) is False


def test_timeout_without_numbers_is_lost() -> None:
    lost = adopt_usage(None, timeout=True)
    assert lost is LOST_ON_TIMEOUT
    assert lost.to_sealed() == {"unavailable": "lost_on_timeout"}
    upgraded = adopt_usage(NOT_REPORTED, timeout=True)
    assert upgraded is LOST_ON_TIMEOUT


def test_timeout_with_numbers_is_partial_and_not_billed() -> None:
    partial = adopt_usage(
        {"input_tokens": 9, "output_tokens": 2, "cached_read_tokens": 1, "cost_usd": 0.5},
        timeout=True,
    )
    assert isinstance(partial, UsageUnavailable)
    assert partial.reason == "partial"
    assert partial.to_sealed() == {
        "prompt_tokens": 9,
        "completion_tokens": 2,
        "cached_tokens": 1,
        "cost_usd": 0.5,
        "unavailable": "partial",
    }
    assert is_measured_usage(partial) is False
    assert bool(partial) is True
    again = adopt_usage(partial, partial=True)
    assert again == partial


def test_parse_failed_does_not_invent_tokens() -> None:
    failed = adopt_usage({"prompt_tokens": 3}, parse_failed=True)
    assert isinstance(failed, UsageUnavailable)
    assert failed.reason == "parse_failed"
    assert failed.prompt_tokens == 3
    bare = adopt_usage("not-json", parse_failed=True)
    assert isinstance(bare, UsageUnavailable)
    assert bare.reason == "parse_failed"
    assert bare.to_sealed() == {"unavailable": "parse_failed"}


def test_marked_unavailable_mapping_is_kept() -> None:
    marked = adopt_usage({"unavailable": "lost_on_timeout", "prompt_tokens": 8})
    assert isinstance(marked, UsageUnavailable)
    assert marked.reason == "lost_on_timeout"
    assert marked.prompt_tokens == 8
    zero = Usage(prompt_tokens=0, completion_tokens=0)
    assert bool(zero) is True
    assert is_measured_usage(zero) is True
    assert is_measured_usage({"unavailable": "partial", "prompt_tokens": 1}) is False
