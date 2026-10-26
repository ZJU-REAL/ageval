"""probe and attach for the local box, and an absent docker handle."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from pathlib import Path

import pytest
from tests.helpers.box import box_spec, local_box

from ageval.environments.box_state import write_cursor, write_inflight, write_nonce
from ageval.environments.protocol import BoxSpec
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.docker.images import daemon_available


def test_local_probe_idle_busy_and_attach(tmp_path: Path) -> None:
    host = local_box(tmp_path / "box")
    absent = asyncio.run(host.probe({}))
    assert absent.status == "absent"

    asyncio.run(host.start())
    write_nonce(host.state_root, "nce_test")
    write_cursor(host.state_root, seq=4, request_id="req_4")
    idle = asyncio.run(host.probe(host.runtime_handle()))
    assert idle.status == "idle"
    assert idle.nonce == "nce_test"
    assert idle.cursor_seq == 4

    write_inflight(host.state_root, pid=os.getpid(), request_id="call_live")
    busy = asyncio.run(host.probe({}))
    assert busy.status == "busy"
    assert busy.inflight_request_id == "call_live"

    write_inflight(host.state_root, pid=2**31 - 1, request_id="call_dead")
    dead = asyncio.run(host.probe({}))
    assert dead.status == "idle"

    fresh = local_box(host.root)
    asyncio.run(fresh.attach({}))
    assert fresh.reattached is True
    assert fresh.placement().target_id.startswith("local:")


def test_local_stop_delete_removes_state_and_publishes_its_path(tmp_path: Path) -> None:
    host = local_box(tmp_path / "box")
    asyncio.run(host.start())
    assert host._child_env({})["AGEVAL_STATE_DIR"] == str(host.state_root)
    (host.state_root / "nonce").write_text("nce", encoding="utf-8")
    asyncio.run(host.stop(delete=False))
    assert host.root.is_dir()
    assert host.state_root.is_dir()

    fresh = local_box(tmp_path / "box")
    asyncio.run(fresh.start())
    (fresh.state_root / "nonce").write_text("nce", encoding="utf-8")
    asyncio.run(fresh.stop(delete=True))
    assert not fresh.root.exists()
    assert not fresh.state_root.exists()


def test_docker_stop_delete_removes_state_beside_the_box(tmp_path: Path) -> None:
    host = DockerHost(spec=box_spec(tmp_path / "box"))
    host.root.mkdir()
    host.state_root.mkdir()
    (host.state_root / "nonce").write_text("nce", encoding="utf-8")
    asyncio.run(host.stop(delete=True))
    assert not host.root.exists()
    assert not host.state_root.exists()


def test_local_exec_streams_output_while_the_process_is_busy(tmp_path: Path) -> None:
    host = local_box(tmp_path / "box")
    asyncio.run(host.start())
    try:
        asyncio.run(_assert_local_partial(host))
    finally:
        asyncio.run(host.stop(delete=True))


async def _assert_local_partial(host):
    task = asyncio.create_task(
        host.exec(
            [
                "python3",
                "-u",
                "-c",
                "print('partial', flush=True); import time; time.sleep(30)",
            ],
            request_id="call_live",
        )
    )
    output = host.state_root / "inflight.output"
    deadline = time.monotonic() + 5
    text = ""
    while time.monotonic() < deadline:
        text = output.read_text(encoding="utf-8") if output.is_file() else ""
        probe = await host.probe({})
        if "partial" in text and probe.status == "busy":
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail(f"output never streamed: {text!r}")
    pid = int((host.state_root / "inflight.pid").read_text(encoding="utf-8").strip())
    os.killpg(pid, signal.SIGTERM)
    result = await task
    assert "partial" in result.stdout
    idle = await host.probe({})
    assert idle.status == "idle"
    assert not (host.state_root / "inflight.pid").is_file()


def test_docker_exec_keeps_last_exit_in_state(tmp_path: Path) -> None:
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")
    asyncio.run(_assert_docker_exec(tmp_path))


async def _assert_docker_exec(tmp_path: Path) -> None:
    host = DockerHost(
        spec=BoxSpec(
            attempt_root=tmp_path / "box",
            task_root=tmp_path,
            repo_root=tmp_path,
        ),
        options={"image": "python:3.12-slim", "user": "root"},
    )
    await host.start()
    try:
        running = asyncio.create_task(
            host.exec(
                [
                    "python3",
                    "-u",
                    "-c",
                    "print('partial', flush=True); import time; time.sleep(30)",
                ],
                request_id="call_live",
            )
        )
        output = host.state_root / "inflight.output"
        deadline = time.monotonic() + 30
        text = ""
        probe = None
        while time.monotonic() < deadline:
            text = output.read_text(encoding="utf-8") if output.is_file() else ""
            probe = await host.probe(host.runtime_handle())
            if "partial" in text and probe.status == "busy":
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"docker output never streamed: {text!r} probe={probe}")
        pid = (host.state_root / "inflight.pid").read_text(encoding="utf-8").strip()
        await host.exec(["sh", "-c", f"kill -TERM {pid}"])
        await running
        result = await host.exec(["python3", "-c", "print('hi')"], request_id="call_1")
        assert result.exit_code == 0
        assert "hi" in result.stdout
        last = json.loads((host.state_root / "last_exit.json").read_text(encoding="utf-8"))
        assert last["request_id"] == "call_1"
        assert last["exit_code"] == 0
        assert "hi" in last["stdout"]
        assert not (host.state_root / "inflight.pid").is_file()
        assert not (host.root / "last_exit.json").is_file()
    finally:
        await host.stop(delete=True)


def test_docker_missing_container_is_absent(tmp_path: Path) -> None:
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")
    host = DockerHost(spec=box_spec(tmp_path / "box"))
    status = asyncio.run(host.probe({"container_id": "ageval-not-a-container"}))
    assert status.status == "absent"
