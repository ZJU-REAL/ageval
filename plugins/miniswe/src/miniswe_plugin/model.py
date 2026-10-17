"""Miniswe HTTP mapping for the core ``ModelSpec``.

The field table lives in ``docs/design/16-model.md``. This module does not
parse profiles. ``wire_body`` and ``transport_clocks`` turn one spec into the
request this plugin sends.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ageval.model import API_CHAT, API_RESPONSES, ModelConfigError, ModelSpec, resolve_model
from ageval.runtime.clocks import ClockError, clock_seconds

DEFAULT_MODEL_ID = "openai/gpt-4o-mini"

__all__ = [
    "API_CHAT",
    "API_RESPONSES",
    "DEFAULT_MODEL_ID",
    "ModelConfigError",
    "ModelSpec",
    "resolve_model",
    "transport_clocks",
    "wire_body",
]


def transport_clocks(spec: ModelSpec) -> tuple[float | None, float]:
    """``(http_timeout, watchdog)``.

    HTTP timeout ``None`` means the client has no timeout. An omitted watchdog
    uses the ``watchdog`` row. Zero and non-finite values fail and do not
    become that default.
    """
    try:
        watchdog = clock_seconds("watchdog", spec.watchdog)
    except ClockError as exc:
        raise ModelConfigError(f"miniswe_watchdog_invalid:{spec.watchdog!r}") from exc
    return spec.timeout, watchdog


def wire_body(spec: ModelSpec) -> dict[str, Any]:
    """Body fields taken from the spec. Unset effort and timeout are absent.

    Chat sends ``reasoning_effort`` only when effort is set. Responses sends
    ``reasoning.effort``, merged over ``extra.reasoning``, with effort last.
    ``extra`` is copied first so a first-class value wins.
    """
    body: dict[str, Any] = copy.deepcopy(dict(spec.extra))
    if spec.api == API_CHAT:
        if spec.reasoning_effort is not None:
            body["reasoning_effort"] = spec.reasoning_effort
    elif spec.api == API_RESPONSES:
        if spec.reasoning_effort is not None:
            current = body.get("reasoning")
            if current is not None and not isinstance(current, Mapping):
                raise ModelConfigError(f"miniswe_model_reasoning_invalid:{current!r}")
            merged: dict[str, Any] = dict(current) if isinstance(current, Mapping) else {}
            merged["effort"] = spec.reasoning_effort
            body["reasoning"] = merged
    else:
        raise ModelConfigError(f"miniswe_api_invalid:{spec.api!r}")
    if spec.timeout is not None:
        body["timeout"] = float(spec.timeout)
    return body
