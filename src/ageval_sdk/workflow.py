"""Bounded async helpers — no Run/Trial/Campaign authority."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Sequence
from typing import Any


def _close_awaitable(aw: Awaitable[Any]) -> None:
    close = getattr(aw, "close", None)
    if callable(close):
        close()


async def bounded_gather[T](
    aws: Sequence[Awaitable[T]],
    *,
    limit: int,
    timeout: float | None = None,
) -> list[T | BaseException]:
    """Wait for every awaitable, in input order, with at most ``limit`` running.

    An ``Exception`` from one child stays in that child's slot. ``CancelledError``
    from this gather propagates. ``timeout`` keeps finished values, puts
    ``TimeoutError`` in the unfinished slots, and drains the rest.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    sem = asyncio.Semaphore(limit)

    async def run_one(aw: Awaitable[T]) -> T | Exception:
        try:
            await sem.acquire()
        except asyncio.CancelledError:
            _close_awaitable(aw)
            raise
        try:
            try:
                return await aw
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — gather slot returns the exception object
                return exc
        finally:
            sem.release()

    tasks = [asyncio.create_task(run_one(aw)) for aw in aws]
    try:
        if timeout is None:
            return [await task for task in tasks]
        if not tasks:
            return []
        done, _pending = await asyncio.wait(set(tasks), timeout=timeout)
        results: list[T | BaseException] = []
        for task in tasks:
            if task in done and not task.cancelled():
                exc = task.exception()
                results.append(exc if exc is not None else task.result())
            else:
                if not task.done():
                    task.cancel()
                results.append(TimeoutError())
        return results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def first_success[T](
    aws: Iterable[Coroutine[Any, Any, T]],
    *,
    limit: int | None = None,
    accept: Callable[[T], bool] | None = None,
) -> T:
    """Return the first result that is not an exception and passes ``accept``.

    With no ``accept``, success means the child returned. It does not mean the
    task is correct and it is not evaluator PASS. ``limit`` caps how many
    children run at once; ``None`` starts them all. A winner cancels the rest,
    including children still waiting for the limit. Exhaustion raises
    ``RuntimeError("no acceptable result")``.
    """
    coros = list(aws)
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")
    if not coros:
        raise RuntimeError("no acceptable result")
    width = len(coros) if limit is None else limit
    waiting = list(coros)
    active: set[asyncio.Task[T]] = set()
    try:
        while waiting or active:
            while waiting and len(active) < width:
                active.add(asyncio.create_task(waiting.pop(0)))
            if not active:
                break
            done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    continue
                result = task.result()
                if accept is not None and not accept(result):
                    continue
                for other in active:
                    other.cancel()
                for coro in waiting:
                    coro.close()
                waiting.clear()
                if active:
                    await asyncio.gather(*active, return_exceptions=True)
                return result
        raise RuntimeError("no acceptable result")
    finally:
        for task in active:
            if not task.done():
                task.cancel()
        for coro in waiting:
            coro.close()
        if active:
            await asyncio.gather(*active, return_exceptions=True)


async def collect_results(values: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for v in values:
        if hasattr(v, "__await__"):
            out.append(await v)  # type: ignore[misc]
        else:
            out.append(v)
    return out
