"""Executor failure families.

The parent stall retries only ``TransportStall``. A wrong profile is
``ModelConfigError``. A body the client cannot decode is ``ProtocolError``.
An action the harness cannot parse is ``FormatError``. None of those three
enter the stall loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FATAL_INVOKE_TITLE = "agent_invoke_failed"
FATAL_INVOKE_PAYLOAD_KEY = "fatal_invoke_kind"
FATAL_INVOKE_KINDS = frozenset({"ModelConfigError", "TransportStall", "StallExhausted"})


class ModelConfigError(Exception):
    """Malformed or unsupported model profile. Not a stall."""

    kind: str = "model_config"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TransportStall(Exception):
    """A transport failure the parent may stall-retry."""

    def __init__(self, message: str, *, kind: str = "transport") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class StallExhausted(Exception):
    """A parent-loop executor exhausted its transport retry budget."""

    def __init__(self, message: str, *, kind: str = "stall_exhausted") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class ProtocolError(Exception):
    """A provider payload the client cannot decode. Not a stall."""

    def __init__(self, message: str, *, kind: str = "protocol") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class FormatError(Exception):
    """An action or tool payload the harness cannot parse. Not a stall."""

    def __init__(self, message: str, *, kind: str = "format") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# HTTP 4xx answers that a retry can change: request timeout and rate limit.
_RETRYABLE_4XX = frozenset({408, 429})


def http_status_is_config_error(code: int) -> bool:
    """True when an upstream HTTP status means the request itself is wrong.

    Any 4xx except 408 and 429 (bad model id, bad field, auth, missing
    route) is a model config error: sending the same request again cannot
    succeed, so it must not go through upstream stall.
    """
    return 400 <= code < 500 and code not in _RETRYABLE_4XX


def classify_fatal_invoke(
    *,
    error: str | None = None,
    failure: BaseException | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str | None:
    """Return the fatal run-invoke kind, or None for an ordinary task failure.

    A stall that the parent recovered ends with ``ok=True`` and never reaches
    this classifier. Exhausted stall budgets and non-retryable 4xx model
    configuration errors do.
    """
    if isinstance(failure, StallExhausted) or type(failure).__name__ == "StallExhausted":
        return "StallExhausted"
    if error == "stall_exhausted":
        return "StallExhausted"
    if metadata is not None and metadata.get("stall_exhausted") is True:
        return "StallExhausted"
    if isinstance(failure, ModelConfigError) or (
        isinstance(error, str) and error.startswith("ModelConfigError")
    ):
        return "ModelConfigError"
    if isinstance(failure, TransportStall) or (
        isinstance(error, str) and error.startswith("TransportStall")
    ):
        return "TransportStall"
    return None


def typed_fatal_failure(kind: str, detail: str) -> BaseException | None:
    """Build the typed failure for a worker-reported fatal invoke kind."""
    if kind == "ModelConfigError":
        return ModelConfigError(detail)
    if kind == "TransportStall":
        return TransportStall(detail, kind="worker")
    if kind == "StallExhausted":
        return StallExhausted(detail)
    return None


def fatal_invoke_detail(
    kind: str,
    *,
    error: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Bounded operator detail; the stable title stays ``agent_invoke_failed``."""
    reason = metadata.get("reason") if isinstance(metadata, Mapping) else None
    detail = error or (reason if isinstance(reason, str) else "") or kind
    if not detail.startswith(kind):
        detail = f"{kind}:{detail}"
    return detail[:500]


def fatal_invoke_failure(
    *,
    error: str | None = None,
    failure: BaseException | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[str, str] | None:
    kind = classify_fatal_invoke(error=error, failure=failure, metadata=metadata)
    if kind is None:
        return None
    detail = error
    if detail is None and kind != "StallExhausted" and failure is not None:
        detail = str(getattr(failure, "message", None) or failure)
    return kind, fatal_invoke_detail(kind, error=detail, metadata=metadata)


def is_fatal_invoke_payload(payload: Mapping[str, Any]) -> bool:
    """True for one completed activity invoke that must not be replayed."""
    if payload.get("ok") is True:
        return False
    stored = payload.get(FATAL_INVOKE_PAYLOAD_KEY)
    if isinstance(stored, str) and stored in FATAL_INVOKE_KINDS:
        return True
    error = payload.get("error")
    return classify_fatal_invoke(error=error if isinstance(error, str) else None) is not None


def is_recoverable_agent_invoke_error(error: object) -> bool:
    """True for the sealed ERROR shape that resumes in the same Attempt."""
    if not isinstance(error, Mapping):
        return False
    return error.get("phase") == "run" and error.get("title") == FATAL_INVOKE_TITLE


def is_recoverable_agent_invoke_result(result: object) -> bool:
    """True for a sealed ERROR result whose failed invoke can resume in place."""
    if not isinstance(result, Mapping) or result.get("status") != "ERROR":
        return False
    return is_recoverable_agent_invoke_error(result.get("error"))
