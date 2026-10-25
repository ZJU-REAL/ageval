"""probe and attach for the local box, and an absent docker handle."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from ageval.environments.box_state import write_cursor, write_inflight, write_nonce
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.docker.images import daemon_available
from tests.helpers.box import box_spec, local_box


def test_local_probe_idle_busy_and_attach(tmp_path: Path) -> None:
    host = local_box(tmp_path / "box")
    absent = asyncio.run(host.probe({}))
    assert absent.status == "absent"

    asyncio.run(host.start())
    write_nonce(host.root, "nce_test")
    write_cursor(host.root, seq=4, request_id="req_4")
    idle = asyncio.run(host.probe(host.runtime_handle()))
    assert idle.status == "idle"
    assert idle.nonce == "nce_test"
    assert idle.cursor_seq == 4

    write_inflight(host.root, pid=os.getpid(), request_id="call_live")
    busy = asyncio.run(host.probe({}))
    assert busy.status == "busy"
    assert busy.inflight_request_id == "call_live"

    write_inflight(host.root, pid=2**31 - 1, request_id="call_dead")
    dead = asyncio.run(host.probe({}))
    assert dead.status == "idle"

    fresh = local_box(host.root)
    asyncio.run(fresh.attach({}))
    assert fresh.reattached is True
    assert fresh.placement().target_id.startswith("local:")


def test_docker_missing_container_is_absent(tmp_path: Path) -> None:
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")
    host = DockerHost(spec=box_spec(tmp_path / "box"))
    status = asyncio.run(host.probe({"container_id": "ageval-not-a-container"}))
    assert status.status == "absent"
