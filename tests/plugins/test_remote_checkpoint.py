"""Remote checkpoint deltas and probe parsing. No cloud credentials required."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from ageval.environments.protocol import BoxSpec, ExecResult
from ageval.environments.remote_state import (
    CHECKPOINT_SYNC_SCRIPT,
    apply_checkpoint_tar,
    parse_state_document,
    push_restored_tree,
)
from ageval.plugins.contrib.daytona.host import DaytonaHost
from ageval.plugins.contrib.e2b.host import E2BHost
from ageval.plugins.contrib.ssh.host import SSHHost


def _spec(tmp_path: Path) -> BoxSpec:
    return BoxSpec(attempt_root=tmp_path, task_root=tmp_path, repo_root=tmp_path)


def test_dump_document_marks_an_inflight_pid_busy() -> None:
    raw = json.dumps(
        {
            "nonce": "nce_1",
            "cursor": {"seq": 4, "request_id": "seq_4"},
            "inflight_pid": 42,
            "inflight_request": "call_1",
            "last_exit": None,
        }
    )
    status = parse_state_document(raw)
    assert status.status == "busy"
    assert status.nonce == "nce_1"
    assert status.cursor_seq == 4
    assert status.inflight_request_id == "call_1"


def test_checkpoint_script_packs_only_changed_files(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    (root / "workspace").mkdir(parents=True)
    (root / "workspace" / "note.txt").write_text("one\n", encoding="utf-8")
    script = tmp_path / "checkpoint_sync.py"
    script.write_text(CHECKPOINT_SYNC_SCRIPT, encoding="utf-8")
    env = os.environ.copy()
    env["AGEVAL_BOX_ROOT"] = str(root)
    out = tmp_path / "delta.tar"
    first = subprocess.run(
        [sys.executable, str(script), "pack", str(out)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    box = tmp_path / "box"
    assert apply_checkpoint_tar(box, out.read_bytes()) == 1
    assert (box / "workspace" / "note.txt").read_text(encoding="utf-8") == "one\n"
    second = subprocess.run(
        [sys.executable, str(script), "pack", str(out)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert apply_checkpoint_tar(tmp_path / "again", out.read_bytes()) == 0


def test_remote_probe_without_a_handle_is_absent(tmp_path: Path) -> None:
    e2b = E2BHost(spec=_spec(tmp_path / "e2b"))
    daytona = DaytonaHost(spec=_spec(tmp_path / "daytona"))
    ssh = SSHHost(spec=_spec(tmp_path / "ssh"), options={"host": "example.invalid"})
    assert asyncio.run(e2b.probe({})).status == "absent"
    assert asyncio.run(daytona.probe({})).status == "absent"
    assert asyncio.run(ssh.probe({})).status == "absent"
    assert e2b.runtime_handle() == {}
    assert daytona.runtime_handle() == {}


def test_dead_inflight_pid_is_idle_and_keeps_last_exit(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    state = root / ".ageval-state"
    state.mkdir(parents=True)
    (state / "nonce").write_text("nce_9", encoding="utf-8")
    (state / "inflight.pid").write_text("99999999\n", encoding="utf-8")
    (state / "inflight.request").write_text("call_9", encoding="utf-8")
    (state / "last_exit.json").write_text(
        json.dumps({"request_id": "call_8", "exit_code": 0, "stdout": "ok", "stderr": ""}),
        encoding="utf-8",
    )
    script = tmp_path / "checkpoint_sync.py"
    script.write_text(CHECKPOINT_SYNC_SCRIPT, encoding="utf-8")
    env = os.environ.copy()
    env["AGEVAL_BOX_ROOT"] = str(root)
    dumped = subprocess.run(
        [sys.executable, str(script), "dump"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert dumped.returncode == 0, dumped.stderr
    status = parse_state_document(dumped.stdout)
    assert status.status == "idle"
    assert status.last_exit is not None
    assert status.last_exit["request_id"] == "call_8"
    assert status.inflight_request_id is None


def test_ssh_probe_and_attach_cover_directory_and_container(tmp_path: Path) -> None:
    host = SSHHost(spec=_spec(tmp_path), options={"host": "example.invalid"})
    payload = json.dumps(
        {
            "nonce": "nce_2",
            "cursor": {"seq": 3, "request_id": "seq_3"},
            "inflight_pid": None,
            "inflight_request": "",
            "last_exit": {"request_id": "call_2", "exit_code": 0, "stdout": "", "stderr": ""},
        }
    )

    async def fake_ssh(argv, *, timeout_sec):
        del argv, timeout_sec
        return ExecResult(exit_code=0, stdout=payload)

    host._ssh = fake_ssh  # type: ignore[method-assign]
    directory = asyncio.run(
        host.probe({"host": "remote.example", "remote_root": "/tmp/ageval-a", "user": "me"})
    )
    assert directory.status == "idle"
    assert directory.last_exit is not None
    assert directory.last_exit["request_id"] == "call_2"
    asyncio.run(
        host.attach(
            {
                "host": "remote.example",
                "remote_root": "/tmp/ageval-a",
                "user": "me",
                "container_id": "cid-1",
            }
        )
    )
    handle = host.runtime_handle()
    assert handle["remote_root"] == "/tmp/ageval-a"
    assert handle["container_id"] == "cid-1"
    assert host._started is True


def test_e2b_attach_reuses_the_connected_sandbox(tmp_path: Path, monkeypatch) -> None:
    payload = json.dumps(
        {
            "nonce": "nce_3",
            "cursor": {"seq": 1, "request_id": "seq_1"},
            "inflight_pid": None,
            "inflight_request": "",
            "last_exit": {"request_id": "call_3", "exit_code": 0, "stdout": "hi", "stderr": ""},
        }
    )

    class Files:
        def make_dir(self, path: str) -> None:
            del path

        def write(self, path: str, data: str) -> None:
            del path, data

    class Commands:
        def run(self, line: str, **kwargs: object):
            del line, kwargs
            return type("R", (), {"exit_code": 0, "stdout": payload, "stderr": ""})()

    class Sandbox:
        sandbox_id = "sbx_1"
        files = Files()
        commands = Commands()

        @staticmethod
        def connect(sid: str) -> Sandbox:
            assert sid == "sbx_1"
            return Sandbox()

    monkeypatch.setattr(
        "ageval.plugins.contrib.e2b.host._import_sdk",
        lambda: type("SDK", (), {"Sandbox": Sandbox})(),
    )
    host = E2BHost(spec=_spec(tmp_path))
    status = asyncio.run(host.probe({"sandbox_id": "sbx_1"}))
    assert status.status == "idle"
    assert status.last_exit is not None
    assert status.last_exit["stdout"] == "hi"
    asyncio.run(host.attach({"sandbox_id": "sbx_1"}))
    assert host.runtime_handle() == {"sandbox_id": "sbx_1"}
    assert host._started is True


def test_daytona_probe_reads_last_exit(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "nonce": "nce_4",
            "cursor": {"seq": 2, "request_id": "seq_2"},
            "inflight_pid": None,
            "inflight_request": "",
            "last_exit": {"request_id": "call_4", "exit_code": 0, "stdout": "", "stderr": ""},
        }
    )

    class Process:
        def exec(self, line: str, **kwargs: object):
            del line, kwargs
            return type("R", (), {"result": payload, "exit_code": 0})()

    class Files:
        def upload_file(self, data: bytes, path: str) -> None:
            del data, path

    sandbox = type("Box", (), {"id": "day_1", "process": Process(), "fs": Files()})()

    class Client:
        def get(self, sid: str):
            assert sid == "day_1"
            return sandbox

    host = DaytonaHost(spec=_spec(tmp_path))
    host._connect_client = lambda: Client()  # type: ignore[method-assign]
    status = asyncio.run(host.probe({"sandbox_id": "day_1"}))
    assert status.status == "idle"
    assert status.last_exit is not None
    assert status.last_exit["request_id"] == "call_4"
    asyncio.run(host.attach({"sandbox_id": "day_1"}))
    assert host.runtime_handle() == {"sandbox_id": "day_1"}


def test_push_restored_tree_uploads_workspace_and_state(tmp_path: Path) -> None:
    box = tmp_path / "box"
    (box / "workspace").mkdir(parents=True)
    (box / "workspace" / "note.txt").write_text("kept\n", encoding="utf-8")
    (box / ".ageval-state").mkdir()
    (box / ".ageval-state" / "nonce").write_text("nce\n", encoding="utf-8")
    seen: list[tuple[Path, str]] = []

    class Host:
        async def upload(self, source: Path, dest: str, service: str | None = None) -> None:
            del service
            seen.append((source, dest))

    asyncio.run(push_restored_tree(Host(), box))
    assert (box / "workspace", "/attempt/workspace") in seen
    assert (box / ".ageval-state", "/attempt/.ageval-state") in seen
