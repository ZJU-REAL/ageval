"""Stall one miniswe model query on the parent invoke's budget.

Messages stay on the running agent. The package tenacity loop is one attempt
for this integration, so the two waits cannot stack. A spent budget raises
``StallExhausted`` and the parent does not start another agent.

After the first ``note_failure``, UpstreamStall freezes the phase clock for the
whole episode — including later query attempts. A sticky gateway hang then no
longer burns ``invoke`` / ``wall_time`` budgets. Cap each attempt with an
explicit request timeout and recycle litellm clients so retries open a fresh
TCP connection instead of reusing a CLOSE-WAIT / idle ESTAB socket.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

_RETRY_ENV = "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"
_POLL_SECONDS = 0.25
# Fallback when the caller does not pass request_timeout (unit tests / legacy).
_DEFAULT_QUERY_TIMEOUT = 180.0


class StallExhausted(Exception):
    """The parent stall budget was spent on this model query."""


_TIMEOUT_HINTS = (
    "timeout",
    "timed out",
    "readtimeout",
    "connecttimeout",
    "connecterror",
    "connectionreset",
    "remoteprotocolerror",
    "serverdisconnected",
    "apitimeouterror",
)


def recycle_llm_clients() -> None:
    """Drop cached litellm HTTP clients so the next query opens a fresh connection.

    Gateway hangs often leave a keep-alive socket ESTAB / CLOSE-WAIT with no
    response bytes. Retrying on the same client reuses that sticky connection;
    closing + flushing forces a new TCP handshake.
    """
    try:
        import inspect

        import litellm
    except Exception:
        return
    cache = getattr(litellm, "in_memory_llm_clients_cache", None)
    if cache is None:
        return
    cached = getattr(cache, "cache_dict", None)
    if isinstance(cached, dict):
        for client in list(cached.values()):
            for target in (
                client,
                getattr(client, "http_client", None),
                getattr(client, "_client", None),
            ):
                if target is None:
                    continue
                closer = getattr(target, "close", None)
                if not callable(closer):
                    continue
                try:
                    result = closer()
                except Exception:
                    continue
                if inspect.isawaitable(result):
                    try:
                        result.close()  # drop un-awaited coroutine
                    except Exception:
                        pass
    flush = getattr(cache, "flush_cache", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass
        return
    clear = getattr(cache, "clear", None)
    if callable(clear):
        try:
            clear()
        except Exception:
            return


def _looks_like_transport_stall(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    blob = f"{name}:{msg}"
    return any(hint in blob for hint in _TIMEOUT_HINTS)


def _call_with_request_timeout(
    query: Callable[..., Any],
    messages: Any,
    kwargs: dict[str, Any],
    request_timeout: float,
) -> Any:
    """Run ``query`` with a hard wall clock. Raises TimeoutError on overrun.

    LiteLLM/OpenAI may sit on a half-dead keep-alive socket past their own
    timeout knobs (module default request_timeout=6000; client Timeout(None)).
    This watchdog is the failsafe that turns a pure hang into an exception the
    stall wrapper can retry after recycling clients.

    Important: do **not** use ``with ThreadPoolExecutor`` — its ``__exit__``
    calls ``shutdown(wait=True)`` and would block until the hung query finishes,
    defeating the timeout. ``shutdown(wait=False)`` lets the wrapper proceed;
    ``recycle_llm_clients`` drops cached sockets so the orphan thread's client
    is not reused.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(query, messages, **kwargs)
        try:
            return fut.result(timeout=request_timeout)
        except FutureTimeout as exc:
            recycle_llm_clients()
            raise TimeoutError(
                f"miniswe_request_timeout:{request_timeout}"
            ) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


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


def wrap_model_query(
    query: Callable[..., Any],
    stall: Any,
    *,
    request_timeout: float | None = None,
) -> Callable[..., Any]:
    """Retry ``query`` with the same messages while the stall budget allows it.

    ``request_timeout`` caps one attempt (seconds). ``None`` uses
    ``_DEFAULT_QUERY_TIMEOUT``. ``0`` disables the watchdog (not recommended).
    """

    timeout = _DEFAULT_QUERY_TIMEOUT if request_timeout is None else float(request_timeout)

    def wrapped(messages: Any, **kwargs: Any) -> Any:
        disable_package_model_retry()
        if stall is None or stall.disabled:
            if timeout > 0:
                return _call_with_request_timeout(query, messages, kwargs, timeout)
            return query(messages, **kwargs)
        while True:
            try:
                if timeout > 0:
                    result = _call_with_request_timeout(query, messages, kwargs, timeout)
                else:
                    result = query(messages, **kwargs)
            except Exception as exc:
                if exc.__class__.__name__ == "FormatError":
                    stall.end_resumed()
                    raise
                reason = f"{type(exc).__name__}:{exc}"
                # Always recycle before a stall retry: sticky sockets are the
                # common hang mode, not only named Timeout errors.
                recycle_llm_clients()
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
