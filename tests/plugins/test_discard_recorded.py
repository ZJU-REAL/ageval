"""Each environment stops a recorded handle without Core inspecting it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ageval.environments.protocol import BoxSpec
from ageval.plugins.contrib.daytona.host import DaytonaHost
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.e2b.host import E2BHost
from ageval.plugins.contrib.local.host import LocalHost
from ageval.plugins.contrib.ssh.host import SSHHost


def _spec(tmp_path: Path) -> BoxSpec:
    return BoxSpec(attempt_root=tmp_path / "box", task_root=tmp_path, repo_root=tmp_path)


def test_docker_discard_removes_the_recorded_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []

    def _docker(*args: object, timeout: float | None = None) -> SimpleNamespace:
        del timeout
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("ageval.plugins.contrib.docker.host.docker", _docker)
    host = DockerHost(spec=_spec(tmp_path))
    asyncio.run(host.discard({"container_id": "c1", "compose_project": "proj"}))
    assert calls == [("rm", "-f", "c1"), ("compose", "-p", "proj", "down")]


def test_e2b_discard_kills_the_recorded_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[str] = []

    class _Sandbox:
        @staticmethod
        def connect(sandbox_id: str) -> _Sandbox:
            killed.append(sandbox_id)
            return _Sandbox()

        def kill(self) -> None:
            killed.append("kill")

    monkeypatch.setattr(
        "ageval.plugins.contrib.e2b.host._import_sdk",
        lambda: SimpleNamespace(Sandbox=_Sandbox),
    )
    host = E2BHost(spec=_spec(tmp_path))
    asyncio.run(host.discard({"sandbox_id": "sbx"}))
    assert killed == ["sbx", "kill"]
    assert host._sandbox is None


def test_daytona_discard_deletes_the_recorded_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[str] = []

    class _Client:
        def get(self, sandbox_id: str) -> str:
            return sandbox_id

        def delete(self, sandbox: str) -> None:
            deleted.append(sandbox)

    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(Daytona=_Client))
    host = DaytonaHost(spec=_spec(tmp_path))
    asyncio.run(host.discard({"sandbox_id": "day"}))
    assert deleted == ["day"]
    assert host._sandbox is None


def test_ssh_directory_is_left_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[list[str]] = []

    async def _ssh(self: SSHHost, argv: list[str], *, timeout_sec: float | None) -> SimpleNamespace:
        del self, timeout_sec
        called.append(list(argv))
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(SSHHost, "_ssh", _ssh)
    host = SSHHost(spec=_spec(tmp_path), options={"host": "box.example"})
    asyncio.run(host.discard({"host": "box.example"}))
    assert called == []


def test_ssh_discard_removes_only_the_recorded_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[list[str]] = []

    async def _ssh(self: SSHHost, argv: list[str], *, timeout_sec: float | None) -> SimpleNamespace:
        del timeout_sec
        assert self._host == "box.example"
        assert self._user == "me"
        called.append(list(argv))
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(SSHHost, "_ssh", _ssh)
    host = SSHHost(spec=_spec(tmp_path), options={"host": "later.example"})
    asyncio.run(
        host.discard({"host": "box.example", "user": "me", "port": "22", "container_id": "c9"})
    )
    assert called == [["docker", "rm", "-f", "c9"]]
    assert host._host == ""


def test_local_discard_keeps_the_directory(tmp_path: Path) -> None:
    host = LocalHost(spec=_spec(tmp_path))
    asyncio.run(host.start())
    asyncio.run(host.discard({"kind": "local"}))
    assert host.root.is_dir()
