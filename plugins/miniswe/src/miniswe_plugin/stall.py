"""Stall one miniswe model query on the parent invoke's budget.

Messages stay on the running agent. The package tenacity loop is one attempt
for this integration, so the two waits cannot stack. A spent budget raises
``StallExhausted`` and the parent does not start another agent.

After the first ``note_failure``, UpstreamStall freezes the phase clock for the
whole episode — including later query attempts. A sticky gateway hang then no
longer burns ``invoke`` / ``wall_time`` budgets. Cap each attempt with an
explicit watchdog, ephemeral no-keepalive OpenAI/httpx clients
(``Connection: close``), and recycle litellm's client cache so retries never
reuse a CLOSE-WAIT / sticky ESTAB socket with a large Send-Q.
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from miniswe_plugin.model import DEFAULT_WATCHDOG_SECONDS, ModelConfigError

_RETRY_ENV = "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"
_POLL_SECONDS = 0.25


class StallExhausted(Exception):
    """The parent stall budget was spent on this model query."""


def recycle_llm_clients() -> None:
    """Drop cached litellm HTTP clients so the next query opens a fresh connection.

    Gateway hangs often leave a keep-alive socket ESTAB / CLOSE-WAIT with a
    large Send-Q and no response bytes. Retrying on the same client reuses that
    sticky connection; closing nested httpx pools + flushing the LiteLLM cache
    forces a new TCP handshake. Implementation lives in ``llm_client``.
    """
    from miniswe_plugin.llm_client import recycle_llm_clients as _recycle

    _recycle()


def _recycle_async() -> None:
    """Fire-and-forget recycle so abandon never blocks on ``close()``.

    Suite hang attempt_1c23ff53: Future timeout + kill_in_flight were present
    but no ``upstream_stall`` logged before SIGTERM at ~4.5 min. ``Client.close``
    does not reliably wake ``_receive_response_headers``; if recycle ever blocks
    on a wedged transport, the TimeoutError never reaches ``wrap_model_query``.
    Run recycle on a daemon thread; ``SHUT_RDWR`` in ``close_llm_client`` does
    the real unblock.
    """
    import threading

    threading.Thread(target=recycle_llm_clients, name="miniswe-recycle", daemon=True).start()


def _require_watchdog(watchdog: float | None) -> float:
    """Omitted watchdog uses the default cap. Zero and non-finite values fail."""
    if watchdog is None:
        return DEFAULT_WATCHDOG_SECONDS
    if isinstance(watchdog, bool):
        raise ValueError(f"miniswe_watchdog_invalid:{watchdog!r}")
    try:
        cap = float(watchdog)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"miniswe_watchdog_invalid:{watchdog!r}") from exc
    if not math.isfinite(cap) or cap <= 0:
        raise ValueError(f"miniswe_watchdog_invalid:{watchdog!r}")
    return cap


def _call_with_watchdog(
    query: Callable[..., Any],
    messages: Any,
    kwargs: dict[str, Any],
    watchdog: float,
) -> Any:
    """Run ``query`` until ``watchdog`` seconds. Raises TimeoutError on overrun.

    LiteLLM/OpenAI may sit on a half-dead keep-alive socket past their own
    HTTP timeout. This Future is the failsafe that turns a pure hang into an
    exception the stall wrapper can retry after recycling clients. It reads
    the watchdog only, not the HTTP client timeout.

    Independent of upstream_stall freeze / ``wait_excluding_stall`` /
    ``wall_time_limit_seconds=0``: those only pause the *parent* invoke/phase
    clocks. This ``fut.result(timeout=…)`` still hard-aborts each LLM attempt.

    Important: do **not** use ``with ThreadPoolExecutor`` — its ``__exit__``
    calls ``shutdown(wait=True)`` and would block until the hung query finishes,
    defeating the timeout. ``shutdown(wait=False)`` lets the wrapper proceed;
    ``_recycle_async`` + ``SHUT_RDWR`` tear down in-flight sockets without
    letting ``close()`` wedge the abandon path.
    """
    cap = _require_watchdog(watchdog)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(query, messages, **kwargs)
        try:
            return fut.result(timeout=cap)
        except FutureTimeout as exc:
            _recycle_async()
            # stderr only: attempt stdout is the agent transcript.
            print(f"miniswe_watchdog:{cap}", file=sys.stderr, flush=True)
            raise TimeoutError(f"miniswe_watchdog:{cap}") from exc
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
    watchdog: float | None = None,
) -> Callable[..., Any]:
    """Retry ``query`` with the same messages while the stall budget allows it.

    ``watchdog`` caps one attempt (seconds). ``None`` uses
    ``DEFAULT_WATCHDOG_SECONDS``. ``0`` and non-finite values are rejected.
    """

    cap = _require_watchdog(watchdog)

    def wrapped(messages: Any, **kwargs: Any) -> Any:
        disable_package_model_retry()
        if stall is None or stall.disabled:
            recycle_llm_clients()
            return _call_with_watchdog(query, messages, kwargs, cap)
        while True:
            # Fresh sockets every attempt — mid-episode keep-alive stickiness
            # (turn2+ ESTAB + large Send-Q) is the observed hang mode.
            recycle_llm_clients()
            try:
                result = _call_with_watchdog(query, messages, kwargs, cap)
            except Exception as exc:
                if exc.__class__.__name__ == "FormatError" or isinstance(exc, ModelConfigError):
                    stall.end_resumed()
                    raise
                reason = f"{type(exc).__name__}:{exc}"
                # Fire-and-forget: sync recycle here re-introduced the boa hang
                # (attempt_06c64f5f) — FutureTimeout had fired but close() on a
                # sticky responses recv could delay TimeoutError reaching
                # note_failure / upstream_stall for many minutes. Daemon +
                # SHUT_RDWR matches _call_with_watchdog abandon.
                _recycle_async()
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
