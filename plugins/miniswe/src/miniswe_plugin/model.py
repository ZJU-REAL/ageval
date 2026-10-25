"""Miniswe HTTP mapping for the core ``ModelSpec``.

The field table lives in ``docs/design/02-schemas-and-config.md``. This module does not
parse profiles. ``wire_body`` and ``transport_clocks`` turn one spec into the
request this plugin sends.
"""

from __future__ import annotations

from typing import Any

from ageval.model import API_CHAT, API_RESPONSES, ModelConfigError, ModelSpec, resolve_model
from ageval.model.wire import chat_body, responses_body
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


def transport_clocks(spec: ModelSpec) -> tuple[float, float]:
    """``(http_timeout, watchdog)``.

    An omitted clock uses its row. Zero and non-finite values fail and do not
    become that default.
    """
    try:
        http_timeout = clock_seconds("timeout", spec.timeout)
    except ClockError as exc:
        raise ModelConfigError(f"miniswe_timeout_invalid:{spec.timeout!r}") from exc
    try:
        watchdog = clock_seconds("watchdog", spec.watchdog)
    except ClockError as exc:
        raise ModelConfigError(f"miniswe_watchdog_invalid:{spec.watchdog!r}") from exc
    return http_timeout, watchdog


def wire_body(spec: ModelSpec) -> dict[str, Any]:
    """Body fields taken from the spec. Unset effort and timeout are absent.

    Chat and responses share ``ageval.model.wire``. ``extra`` is copied first
    so a first-class value wins.
    """
    if spec.api == API_CHAT:
        return chat_body(spec)
    if spec.api == API_RESPONSES:
        return responses_body(spec)
    raise ModelConfigError(f"miniswe_api_invalid:{spec.api!r}")
