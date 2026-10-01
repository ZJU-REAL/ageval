"""Stall one miniswe model query on the parent invoke's budget.

Messages stay on the running agent. The package tenacity loop is one attempt
for this integration, so the two waits cannot stack. A spent budget raises
``StallExhausted`` and the parent does not start another agent.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

_RETRY_ENV = "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"
_POLL_SECONDS = 0.25


class StallExhausted(Exception):
    """The parent stall budget was spent on this model query."""


def disable_package_model_retry() -> None:
    """One package attempt. The parent stall is the only wait."""
    os.environ[_RETRY_ENV] = "1"


def install_single_package_attempt() -> Callable[[], None]:
    """Set the package retry limit to one attempt and return a restore."""
    previous = os.environ.get(_RETRY_ENV)
    disable_package_model_retry()

    def restore() -> None:
        if previous is None:
            os.environ.pop(_RETRY_ENV, None)
        else:
            os.environ[_RETRY_ENV] = previous

    return restore


def wrap_model_query(query: Callable[..., Any], stall: Any) -> Callable[..., Any]:
    """Retry ``query`` with the same messages while the stall budget allows it."""

    def wrapped(messages: Any, **kwargs: Any) -> Any:
        disable_package_model_retry()
        if stall is None or stall.disabled:
            return query(messages, **kwargs)
        while True:
            try:
                result = query(messages, **kwargs)
            except Exception as exc:
                if exc.__class__.__name__ == "FormatError":
                    stall.end_resumed()
                    raise
                reason = f"{type(exc).__name__}:{exc}"
                if stall.note_failure(reason):
                    stall.wait()
                    continue
                raise StallExhausted(reason) from exc
            stall.end_resumed()
            return result

    return wrapped


def wait_excluding_stall(fut: Future[Any], stall: Any, timeout: float) -> Any:
    """Wait for ``fut``. Time while ``stall.is_frozen`` does not consume ``timeout``."""
    deadline = time.monotonic() + timeout
    frozen_at: float | None = None
    while True:
        if stall.is_frozen:
            if frozen_at is None:
                frozen_at = time.monotonic()
            slice_s = _POLL_SECONDS
        else:
            if frozen_at is not None:
                deadline += time.monotonic() - frozen_at
                frozen_at = None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FutureTimeout()
            slice_s = min(_POLL_SECONDS, remaining)
        try:
            return fut.result(timeout=slice_s)
        except FutureTimeout:
            continue
