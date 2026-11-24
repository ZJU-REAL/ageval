"""ACP HOME prep prefers a host directory maker and otherwise mkdir's in the box."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from ageval.environments.protocol import HOME_PATH, EnvironmentFailure, ExecResult
from ageval.plugins.contrib.acp.home import prepare_home, write_lock_overlays
from ageval.plugins.contrib.acp.lock_overlay import OverlayFile
from ageval.plugins.contrib.acp.registry import get_entry


@dataclass
class _ExecHost:
    """A non-docker host: directories are created by exec."""

    uploads: list[tuple[str, str]] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)

    async def exec(self, command, **kwargs: Any) -> ExecResult:  # noqa: ANN001
        del kwargs
        self.commands.append([str(part) for part in command])
        return ExecResult(exit_code=0, stdout="", stderr="")

    async def upload(self, source: str | Path, dest: str) -> None:
        self.uploads.append((str(source), dest))


@dataclass
class _DirHost(_ExecHost):
    made: list[list[str]] = field(default_factory=list)

    def ensure_attempt_dirs(self, paths: list[str]) -> None:
        self.made.append(list(paths))


@dataclass
class _DeniedHost(_DirHost):
    def ensure_attempt_dirs(self, paths: list[str]) -> None:
        self.made.append(list(paths))
        raise PermissionError(paths[0])


def _pi():
    desc = get_entry("pi")
    assert desc is not None
    return desc


def _opencode():
    desc = get_entry("opencode")
    assert desc is not None
    return desc


@pytest.mark.asyncio
async def test_prepare_home_uses_exec_when_the_host_cannot_make_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ageval.plugins.contrib.acp.home.Path.home", lambda: tmp_path)
    host = _ExecHost()
    prepared = await prepare_home(host, _pi())
    assert ".pi/agent" in prepared["dirs"]
    assert host.commands
    assert host.commands[0][0:2] == ["sh", "-c"]
    assert "mkdir -p" in host.commands[0][2]
    assert ".pi/agent" in host.commands[0][2]


@pytest.mark.asyncio
async def test_prepare_home_prefers_the_host_directory_maker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ageval.plugins.contrib.acp.home.Path.home", lambda: tmp_path)
    host = _DirHost()
    await prepare_home(host, _pi())
    assert host.commands == []
    assert host.made
    assert f"{HOME_PATH}/.pi/agent" in host.made[0]
    assert f"{HOME_PATH}/.config" in host.made[0]
    assert all(".." not in path for path in host.made[0])


@pytest.mark.asyncio
async def test_prepare_home_falls_back_to_exec_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ageval.plugins.contrib.acp.home.Path.home", lambda: tmp_path)
    host = _DeniedHost()
    await prepare_home(host, _opencode())
    assert host.made
    assert host.commands
    assert "mkdir -p" in host.commands[0][2]
    assert ".local/share/opencode" in host.commands[0][2]


@pytest.mark.asyncio
async def test_overlay_uses_the_host_directory_maker() -> None:
    host = _DirHost()
    written = await write_lock_overlays(
        host,
        [OverlayFile(dest=".pi/agent/models.json", payload={"providers": {}}, kind="json")],
    )
    assert written == [".pi/agent/models.json"]
    assert host.commands == []
    assert host.made == [[f"{HOME_PATH}/.pi/agent"]]
    assert host.uploads[0][1] == f"{HOME_PATH}/.pi/agent/models.json"


@pytest.mark.asyncio
async def test_overlay_without_the_maker_still_mkdirs_in_the_box() -> None:
    host = _ExecHost()
    written = await write_lock_overlays(
        host,
        [
            OverlayFile(
                dest=".config/opencode/opencode.json",
                payload={"provider": {}},
                kind="json",
            )
        ],
    )
    assert written == [".config/opencode/opencode.json"]
    assert ["mkdir", "-p", ".config/opencode"] in host.commands
    assert host.uploads[0][1] == f"{HOME_PATH}/.config/opencode/opencode.json"


@pytest.mark.asyncio
async def test_overlay_escape_is_rejected_before_any_mkdir() -> None:
    host = _DirHost()
    with pytest.raises(EnvironmentFailure, match="refusing overlay dest"):
        await write_lock_overlays(
            host,
            [OverlayFile(dest="../etc/passwd", payload={}, kind="json")],
        )
    assert host.made == []
    assert host.commands == []
    assert host.uploads == []
