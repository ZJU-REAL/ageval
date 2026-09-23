"""The error object on ``phase_failed``, ``result.json``, and an ERROR suite row.

One shape. The parent does not import the dataset module. A worker envelope
already split ``title`` and ``message`` travels in ``RecordedError``.
"""

from __future__ import annotations

from typing import Any

from ageval.config.errors import ConfigError
from ageval.environments.protocol import EnvironmentFailure

# Parent-side exceptions whose entire text is already the stable token.
_MESSAGE_TOKENS = frozenset(
    {
        "environment_timeout",
        "evaluate_timeout",
        "evaluator_invalid_status",
        "phase_budget_exceeded",
        "unknown_evaluate_environment",
    }
)
_STDERR_TAIL = 500


class RecordedError(RuntimeError):
    """Title and message already taken from a worker envelope."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__(message or title)
        self.error_title = title
        self.error_message = message


def error_record(*, phase: str | None, title: str, message: str) -> dict[str, Any]:
    return {"phase": phase, "title": title, "message": message}


def error_record_from_exception(exc: BaseException, *, phase: str | None) -> dict[str, Any]:
    """Map an exception the parent already holds onto ``phase`` / ``title`` / ``message``."""
    title = getattr(exc, "error_title", None)
    message = getattr(exc, "error_message", None)
    if isinstance(title, str) and title and isinstance(message, str):
        return error_record(phase=phase, title=title, message=message)
    if isinstance(exc, EnvironmentFailure):
        return error_record(phase=phase, title=exc.kind, message=str(exc.message))
    if isinstance(exc, ConfigError):
        return error_record(phase=phase, title="ConfigError", message=str(exc))
    text = str(exc).strip()
    if text in _MESSAGE_TOKENS:
        return error_record(phase=phase, title=text, message=text)
    return error_record(phase=phase, title=type(exc).__name__, message=str(exc))


def message_from_envelope(envelope: dict[str, Any]) -> str:
    """Envelope ``message``, otherwise the bounded stderr tail."""
    message = envelope.get("message")
    if isinstance(message, str) and message:
        return message[-_STDERR_TAIL:]
    stderr = envelope.get("stderr")
    if isinstance(stderr, str) and stderr:
        return stderr[-_STDERR_TAIL:]
    return ""
