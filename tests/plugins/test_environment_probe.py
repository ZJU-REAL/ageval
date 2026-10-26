"""probe and attach for the local box, and an absent docker handle."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
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


def test_local_attach_stdio_is_busy_until_the_process_exits(tmp_path: Path) -> None:
    host = local_box(tmp_path / "box")
    asyncio.run(host.start())
    pipe = None
    try:
        pipe = asyncio.run(
            host.attach_stdio(
                ["sleep", "30"],
                placement=host.placement(),
                request_id="req_acp",
            )
        )
        busy = asyncio.run(host.probe({}))
        assert busy.status == "busy"
        assert busy.inflight_request_id == "req_acp"
        pipe.terminate()
        pipe.wait(timeout=2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (host.state_root / "inflight.pid").is_file():
            time.sleep(0.05)
        idle = asyncio.run(host.probe({}))
        assert idle.status == "idle"
        assert not (host.state_root / "inflight.pid").is_file()
    finally:
        if pipe is not None:
            pipe.terminate()
        asyncio.run(host.stop(delete=True))


def test_live_stdio_pid_blocks_recovery_attach(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from ageval.attempt.ctx import AttemptCtx
    from ageval.attempt.recover import classify_environment, write_attempt_header
    from ageval.evidence.activity import ActivityLog
    from ageval.evidence.store import AttemptEvidenceStore
    from ageval.plugins.protocol import ExtensionGraph
    from ageval.plugins.registry import ExtensionRegistry
    from ageval.plugins.services import ServiceTable
    from ageval.runtime.cancellation import CancellationSignal

    host = local_box(tmp_path / "box")
    asyncio.run(host.start())
    write_nonce(host.state_root, "nce_test")
    pipe = None
    try:
        pipe = asyncio.run(
            host.attach_stdio(["sleep", "30"], placement=host.placement(), request_id="req_acp")
        )
        log = ActivityLog.open(tmp_path / "activity.jsonl")
        write_attempt_header(
            log,
            run_id="r",
            trial_id="t",
            attempt_id="a",
            task_id="task",
            attempt_index=0,
            suite_run_id=None,
            digest="sha256:abc",
            environment_kind="local",
            nonce="nce_test",
        )
        past = (datetime.now(UTC) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        log.append(
            request_id="call_1",
            kind="tool_call",
            status="in_flight",
            payload={
                "session_id": "sess",
                "invoke_request_id": "req_acp",
                "tool_call_id": "call_1",
                "tool_name": "execute",
                "tool_kind": "execute",
                "arguments": {},
                "replay_safe": False,
                "system_effect": False,
                "timeout_sec": None,
                "deadline_utc": past,
            },
        )
        evidence = AttemptEvidenceStore(root=tmp_path / "run", attempt_id="a", run_id="r")
        ctx = AttemptCtx(
            run_id="r",
            trial_id="t",
            attempt_id="a",
            lock=None,  # type: ignore[arg-type]
            profile_id="solver",
            bindings=ExtensionGraph(profile_id="solver"),
            registry=ExtensionRegistry(),
            services=ServiceTable(),
            host=host,  # type: ignore[arg-type]
            evidence=evidence,
            cancellation=CancellationSignal(),
            task_root=tmp_path,
            dataset_root=tmp_path,
            activity=log,
        )
        started: list[str] = []
        original_start = host.start
        original_stdio = host.attach_stdio

        async def _start(*args: object, **kwargs: object) -> None:
            started.append("start")
            await original_start(*args, **kwargs)  # type: ignore[arg-type]

        async def _stdio(*args: object, **kwargs: object):  # noqa: ANN202
            started.append("attach_stdio")
            return await original_stdio(*args, **kwargs)  # type: ignore[arg-type]

        host.start = _start  # type: ignore[method-assign]
        host.attach_stdio = _stdio  # type: ignore[method-assign]
        decision = asyncio.run(classify_environment(ctx))
        assert decision == "busy"
        assert started == []
        assert host.reattached is False
        assert not (evidence.root / "result.json").is_file()
    finally:
        if pipe is not None:
            pipe.terminate()
        asyncio.run(host.stop(delete=True))


def _dash_argv(argv: list[str]) -> list[str]:
    """Run a shipped ``sh`` wrapper under dash.

    macOS ``sh`` is bash. Ubuntu CI ``sh`` is dash. A bash pass hides a dash
    stdin bug, so this test fails closed when dash is not installed.
    """
    dash = shutil.which("dash")
    if dash is None:
        pytest.fail("install dash (brew install dash); macOS sh is bash and does not match CI")
    wrapped = list(argv)
    wrapped[0] = dash
    return wrapped


def test_docker_exec_wrapper_forwards_stdin(tmp_path: Path) -> None:
    import os
    import subprocess

    from ageval.plugins.contrib.docker.host import _exec_pid_wrapper

    env = os.environ.copy()
    env["AGEVAL_STATE_DIR"] = str(tmp_path)
    env["AGEVAL_EXEC_REQUEST"] = "req_stdin"
    argv = _dash_argv(
        _exec_pid_wrapper(["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"])
    )
    proc = subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(b"token-from-parent\n", timeout=15)
    assert proc.returncode == 0, stderr.decode("utf-8", errors="replace")
    assert b"token-from-parent" in stdout
    assert b"token-from-parent" not in stderr


def test_remote_stdio_wrapper_forwards_stdin(tmp_path: Path) -> None:
    import os
    import subprocess

    from ageval.environments.remote_state import stdio_inflight_argv

    env = os.environ.copy()
    env["AGEVAL_STATE_DIR"] = str(tmp_path)
    env["AGEVAL_EXEC_REQUEST"] = "req_remote_stdin"
    argv = _dash_argv(
        stdio_inflight_argv(["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"])
    )
    proc = subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(b"token-from-parent\n", timeout=15)
    assert proc.returncode == 0, stderr.decode("utf-8", errors="replace")
    assert stdout == b"token-from-parent\n"
    assert stderr == b""


def test_stdio_wrapper_is_busy_without_logging_on_stdout(tmp_path: Path) -> None:
    import os
    import select
    import subprocess

    from ageval.environments.remote_state import stdio_inflight_argv

    env = os.environ.copy()
    env["AGEVAL_STATE_DIR"] = str(tmp_path)
    env["AGEVAL_EXEC_REQUEST"] = "req_remote"
    argv = _dash_argv(stdio_inflight_argv(["sleep", "30"]))
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 2
        text = ""
        while time.monotonic() < deadline:
            path = tmp_path / "inflight.pid"
            if path.is_file() and path.read_text(encoding="utf-8").strip():
                text = path.read_text(encoding="utf-8").strip()
                break
            time.sleep(0.05)
        assert text.isdigit()
        assert proc.stdout is not None
        ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        assert ready == []
    finally:
        proc.terminate()
        proc.wait(timeout=2)
    assert not (tmp_path / "inflight.pid").is_file()


def test_docker_attach_stdio_is_busy_until_the_process_exits(tmp_path: Path) -> None:
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")
    asyncio.run(_assert_docker_stdio(tmp_path))


async def _assert_docker_stdio(tmp_path: Path) -> None:
    host = DockerHost(
        spec=BoxSpec(
            attempt_root=tmp_path / "box",
            task_root=tmp_path,
            repo_root=tmp_path,
        ),
        options={"image": "python:3.12-slim", "user": "root"},
    )
    await host.start()
    pipe = None
    try:
        pipe = await host.attach_stdio(
            ["python3", "-c", "import time; time.sleep(30)"],
            placement=host.placement(),
            request_id="req_acp",
        )
        deadline = time.monotonic() + 20
        probe = None
        while time.monotonic() < deadline:
            probe = await host.probe(host.runtime_handle())
            if probe.status == "busy" and (host.state_root / "inflight.pid").is_file():
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"docker stdio never became busy: {probe}")
        pid = (host.state_root / "inflight.pid").read_text(encoding="utf-8").strip()
        await host.exec(["sh", "-c", f"kill -TERM {pid}"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (host.state_root / "inflight.pid").is_file():
            await asyncio.sleep(0.05)
        idle = await host.probe(host.runtime_handle())
        assert idle.status == "idle"
        assert not (host.state_root / "inflight.pid").is_file()
    finally:
        if pipe is not None:
            pipe.terminate()
        await host.stop(delete=True)


def test_docker_missing_container_is_absent(tmp_path: Path) -> None:
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")
    host = DockerHost(spec=box_spec(tmp_path / "box"))
    status = asyncio.run(host.probe({"container_id": "ageval-not-a-container"}))
    assert status.status == "absent"
