"""SDK wait helpers: association, partial failure, and acceptable-result racing."""

from __future__ import annotations

import asyncio

import pytest

from ageval_sdk.workflow import bounded_gather, first_success


def test_bounded_gather_keeps_a_sibling_when_one_child_fails() -> None:
    async def _ok() -> str:
        return "kept"

    async def _bad() -> str:
        raise RuntimeError("child")

    results = asyncio.run(bounded_gather([_ok(), _bad(), _ok()], limit=3))

    assert results[0] == "kept"
    assert isinstance(results[1], RuntimeError)
    assert results[2] == "kept"


def test_bounded_gather_timeout_keeps_finished_work() -> None:
    async def _ok() -> str:
        return "done"

    async def _slow() -> str:
        await asyncio.Event().wait()
        return "late"

    results = asyncio.run(bounded_gather([_ok(), _slow()], limit=2, timeout=0.05))

    assert results[0] == "done"
    assert isinstance(results[1], TimeoutError)


def test_bounded_gather_cancellation_propagates() -> None:
    started = asyncio.Event()

    async def _slow() -> str:
        started.set()
        await asyncio.Event().wait()
        return "late"

    async def _run() -> list[object]:
        task = asyncio.create_task(bounded_gather([_slow(), _slow()], limit=2))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return []

    asyncio.run(_run())


def test_first_success_rejects_a_false_ok_when_asked() -> None:
    async def _reply(ok: bool) -> dict[str, bool]:
        return {"ok": ok}

    result = asyncio.run(
        first_success(
            [_reply(False), _reply(True)],
            accept=lambda reply: reply.get("ok") is True,
        )
    )

    assert result == {"ok": True}


def test_first_success_without_a_predicate_accepts_a_returned_value() -> None:
    async def _reply() -> dict[str, bool]:
        return {"ok": False}

    result = asyncio.run(first_success([_reply()]))

    assert result == {"ok": False}


def test_first_success_exhaustion_is_an_error() -> None:
    async def _bad() -> dict[str, bool]:
        raise RuntimeError("nope")

    async def _false() -> dict[str, bool]:
        return {"ok": False}

    with pytest.raises(RuntimeError, match="no acceptable result"):
        asyncio.run(
            first_success(
                [_bad(), _false()],
                accept=lambda reply: reply.get("ok") is True,
            )
        )


def test_first_success_cancels_children_not_yet_admitted() -> None:
    started: list[str] = []

    async def _child(name: str) -> dict[str, bool]:
        started.append(name)
        if name == "a":
            return {"ok": True}
        await asyncio.Event().wait()
        return {"ok": True}

    result = asyncio.run(
        first_success(
            [_child("a"), _child("b"), _child("c")],
            limit=1,
            accept=lambda reply: reply.get("ok") is True,
        )
    )

    assert result == {"ok": True}
    assert started == ["a"]


def test_first_success_cancels_a_running_loser() -> None:
    started = asyncio.Event()
    released = asyncio.Event()

    async def _slow() -> dict[str, bool]:
        started.set()
        await released.wait()
        return {"ok": False}

    async def _winner() -> dict[str, bool]:
        await started.wait()
        return {"ok": True}

    result = asyncio.run(
        first_success(
            [_slow(), _winner()],
            limit=2,
            accept=lambda reply: reply.get("ok") is True,
        )
    )

    assert result == {"ok": True}
    assert released.is_set() is False


def test_completion_order_can_start_another_child() -> None:
    release = asyncio.Event()

    async def _slow() -> str:
        await release.wait()
        return "slow"

    async def _fast() -> str:
        return "fast"

    async def _extra() -> str:
        return "extra"

    async def _run() -> list[str]:
        active = {asyncio.create_task(_slow()), asyncio.create_task(_fast())}
        done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
        assert [task.result() for task in done] == ["fast"]
        assert len(active) == 1
        active.add(asyncio.create_task(_extra()))
        release.set()
        finished = [task.result() for task in done] + list(await asyncio.gather(*active))
        return finished

    finished = asyncio.run(_run())
    assert finished[0] == "fast"
    assert set(finished[1:]) == {"slow", "extra"}


def test_first_success_replenishes_until_a_winner() -> None:
    started: list[str] = []

    async def _child(name: str, ok: bool) -> dict[str, bool]:
        started.append(name)
        return {"ok": ok}

    result = asyncio.run(
        first_success(
            [_child("a", False), _child("b", False), _child("c", True)],
            limit=1,
            accept=lambda reply: reply.get("ok") is True,
        )
    )

    assert result == {"ok": True}
    assert started == ["a", "b", "c"]
