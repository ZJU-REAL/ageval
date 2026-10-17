"""One chat body and one responses body for every HTTP executor.

``extra`` is copied first. A first-class effort wins. Chat sends top-level
``reasoning_effort`` only when effort is set. Responses merges
``reasoning.effort`` over ``extra.reasoning``, with effort last. An omitted
effort or timeout is absent. ``none`` is a sent value.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ageval.model.errors import ModelConfigError
from ageval.model.spec import ModelSpec


def _base(spec: ModelSpec) -> dict[str, Any]:
    body: dict[str, Any] = copy.deepcopy(dict(spec.extra))
    if spec.timeout is not None:
        body["timeout"] = float(spec.timeout)
    return body


def chat_body(spec: ModelSpec) -> dict[str, Any]:
    """Chat Completions fields taken from one spec."""
    body = _base(spec)
    if spec.reasoning_effort is not None:
        body["reasoning_effort"] = spec.reasoning_effort
    return body


def responses_body(spec: ModelSpec) -> dict[str, Any]:
    """Responses API fields taken from one spec."""
    body = _base(spec)
    if spec.reasoning_effort is None:
        return body
    current = body.get("reasoning")
    if current is not None and not isinstance(current, Mapping):
        raise ModelConfigError(f"model_reasoning_invalid:{current!r}")
    merged: dict[str, Any] = dict(current) if isinstance(current, Mapping) else {}
    merged["effort"] = spec.reasoning_effort
    body["reasoning"] = merged
    return body
