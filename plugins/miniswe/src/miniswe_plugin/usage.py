"""Sum token usage across a mini-swe-agent message list.

Supports both shapes:

* Chat Completions (``LitellmModel``): ``extra.response.usage`` with
  ``prompt_tokens`` / ``completion_tokens``.
* Responses API (``LitellmResponseModel``): the message *is* the response
  object (``object=response``), so usage lives at the top-level
  ``message.usage`` with ``input_tokens`` / ``output_tokens``. There is no
  nested ``extra.response``.

Observational. A zero ``extra.cost`` is a failed price lookup
(``cost_tracking=ignore_errors``), not a measured bill, so it is omitted.
"""

from __future__ import annotations

import math
from typing import Any


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value != int(value) or value < 0:
        return None
    return int(value)


def _as_positive_cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _usage_dict(message: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a usage blob from a chat or Responses message.

    Prefer nested ``extra.response.usage`` (chat). Fall back to top-level
    ``message.usage`` (Responses: message is the dumped response object).
    """
    extra = message.get("extra")
    if isinstance(extra, dict):
        response = extra.get("response")
        if isinstance(response, dict):
            nested = response.get("usage")
            if isinstance(nested, dict):
                return nested
    top = message.get("usage")
    return top if isinstance(top, dict) else None


def _cached_tokens(usage: dict[str, Any]) -> int | None:
    cached_n = _as_int(usage.get("cached_tokens"))
    if cached_n is not None:
        return cached_n
    for details_key in ("prompt_tokens_details", "input_tokens_details"):
        details = usage.get(details_key)
        if isinstance(details, dict):
            cached_n = _as_int(details.get("cached_tokens"))
            if cached_n is not None:
                return cached_n
    return None


def usage_from_messages(messages: Any) -> dict[str, Any] | None:
    """First-class ``terminal.usage`` for one mini-swe-agent run."""
    if not isinstance(messages, list):
        return None
    prompt = completion = cached = 0
    saw_prompt = saw_completion = saw_cached = False
    cost = 0.0
    saw_cost = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        usage = _usage_dict(message)
        if usage is not None:
            prompt_n = _as_int(usage.get("prompt_tokens"))
            if prompt_n is None:
                prompt_n = _as_int(usage.get("input_tokens"))
            completion_n = _as_int(usage.get("completion_tokens"))
            if completion_n is None:
                completion_n = _as_int(usage.get("output_tokens"))
            cached_n = _cached_tokens(usage)
            if prompt_n is not None:
                prompt += prompt_n
                saw_prompt = True
            if completion_n is not None:
                completion += completion_n
                saw_completion = True
            if cached_n is not None:
                cached += cached_n
                saw_cached = True
        extra = message.get("extra")
        if isinstance(extra, dict):
            reported = _as_positive_cost(extra.get("cost"))
            if reported is not None:
                cost += reported
                saw_cost = True
    out: dict[str, Any] = {}
    if saw_prompt:
        out["prompt_tokens"] = prompt
    if saw_completion:
        out["completion_tokens"] = completion
    if saw_cached:
        out["cached_tokens"] = cached
    if saw_cost:
        out["cost_usd"] = cost
    return out or None
