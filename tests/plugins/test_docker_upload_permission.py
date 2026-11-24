"""Host-side upload falls back to docker cp only for permission failures."""

from __future__ import annotations

import errno
import os
import shutil
import stat
from pathlib import Path

import pytest

from ageval.environments.protocol import HOME_PATH, BoxSpec, EnvironmentFailure
from ageval.plugins.contrib.docker.host import DockerHost


def _started_host(tmp_path: Path) -> DockerHost:
    spec = BoxSpec(
        attempt_root=tmp_path / "box",
        task_root=tmp_path,
        repo_root=tmp_path,
    )
    host = DockerHost(spec=spec)
    host._started = True
    host._container = "ageval-test"
    host._prepare_work_root()
    return host


def _snapshot(root: Path) -> set[tuple[str, int]]:
    found: set[tuple[str, int]] = set()
    for path in root.rglob("*"):
        found.add((path.relative_to(root).as_posix(), stat.S_IMODE(path.lstat().st_mode)))
    return found


@pytest.mark.asyncio
async def test_upload_falls_back_when_the_parent_dir_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    parent = host.host_path(f"{HOME_PATH}/.pi/agent")
    parent.mkdir(parents=True)
    parent.chmod(0o555)
    src = tmp_path / "models.json"
    src.write_text('{"ok": true}\n', encoding="utf-8")
    seen: list[str] = []

    async def fake_cp(source: Path, dest: str, *, service: str | None = None) -> None:
        del service
        seen.append(dest)
        parent.chmod(0o755)
        target = host.host_path(dest)
        shutil.copy2(source, target)

    monkeypatch.setattr(host, "_cp_into", fake_cp)
    dest = f"{HOME_PATH}/.pi/agent/models.json"
    try:
        await host.upload(src, dest)
    finally:
        if parent.exists():
            parent.chmod(0o755)
    assert seen == [dest]
    assert host.host_path(dest).read_text(encoding="utf-8") == '{"ok": true}\n'


@pytest.mark.asyncio
async def test_upload_falls_back_when_the_dest_file_is_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    parent = host.host_path(f"{HOME_PATH}/.pi/agent")
    parent.mkdir(parents=True)
    target = parent / "models.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0)
    src = tmp_path / "models.json"
    src.write_text("new\n", encoding="utf-8")
    seen: list[str] = []

    async def fake_cp(source: Path, dest: str, *, service: str | None = None) -> None:
        del service
        seen.append(dest)
        target.chmod(0o644)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(host, "_cp_into", fake_cp)
    dest = f"{HOME_PATH}/.pi/agent/models.json"
    try:
        await host.upload(src, dest)
    finally:
        if target.exists():
            target.chmod(0o644)
    assert seen == [dest]
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_upload_permission_shutil_error_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    src = tmp_path / "tree"
    (src / "nested").mkdir(parents=True)
    (src / "nested" / "note.txt").write_text("x", encoding="utf-8")
    seen: list[str] = []

    def boom(source: Path, dest: Path) -> None:
        del source, dest
        raise shutil.Error([("a", "b", "[Errno 13] Permission denied: 'b'")])

    async def fake_cp(source: Path, dest: str, *, service: str | None = None) -> None:
        del source, service
        seen.append(dest)

    monkeypatch.setattr("ageval.plugins.contrib.docker.host.copy_bind_tree", boom)
    monkeypatch.setattr(host, "_cp_into", fake_cp)
    await host.upload(src, HOME_PATH)
    assert seen == [HOME_PATH]


@pytest.mark.asyncio
async def test_upload_mixed_shutil_error_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    src = tmp_path / "tree"
    src.mkdir()
    (src / "note.txt").write_text("x", encoding="utf-8")
    seen: list[str] = []

    def boom(source: Path, dest: Path) -> None:
        del source, dest
        raise shutil.Error(
            [
                ("a", "b", "[Errno 13] Permission denied: 'b'"),
                ("c", "d", "[Errno 28] No space left on device"),
            ]
        )

    async def fake_cp(source: Path, dest: str, *, service: str | None = None) -> None:
        del source, service
        seen.append(dest)

    monkeypatch.setattr("ageval.plugins.contrib.docker.host.copy_bind_tree", boom)
    monkeypatch.setattr(host, "_cp_into", fake_cp)
    with pytest.raises(shutil.Error):
        await host.upload(src, HOME_PATH)
    assert seen == []


@pytest.mark.asyncio
async def test_upload_non_permission_oserror_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    src = tmp_path / "models.json"
    src.write_text("{}\n", encoding="utf-8")
    seen: list[str] = []

    def boom(source: Path, dest: Path) -> None:
        del source, dest
        raise OSError(errno.ENOSPC, "No space left on device")

    async def fake_cp(source: Path, dest: str, *, service: str | None = None) -> None:
        del source, service
        seen.append(dest)

    monkeypatch.setattr(shutil, "copy2", boom)
    monkeypatch.setattr(host, "_cp_into", fake_cp)
    with pytest.raises(OSError) as raised:
        await host.upload(src, f"{HOME_PATH}/models.json")
    assert raised.value.errno == errno.ENOSPC
    assert seen == []


def test_ensure_attempt_dirs_makes_the_chain_writable_and_leaves_siblings(
    tmp_path: Path,
) -> None:
    host = _started_host(tmp_path)
    home = host.host_path(HOME_PATH)
    sibling = home / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")
    sibling.chmod(0o640)
    host.ensure_attempt_dirs([f"{HOME_PATH}/.pi/agent", f"{HOME_PATH}/.config/opencode"])
    for rel in (".pi", ".pi/agent", ".config", ".config/opencode"):
        path = home / rel
        assert path.is_dir()
        assert not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o777
        assert path.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(sibling.stat().st_mode) == 0o640


def test_ensure_attempt_dirs_rejects_escape_before_mutation(tmp_path: Path) -> None:
    host = _started_host(tmp_path)
    before = _snapshot(host.root)
    with pytest.raises(EnvironmentFailure, match="escapes"):
        host.ensure_attempt_dirs(
            [
                f"{HOME_PATH}/.pi/agent",
                f"{HOME_PATH}/../../etc/ageval-escape",
            ]
        )
    assert _snapshot(host.root) == before
    assert not (tmp_path / "etc" / "ageval-escape").exists()


def test_ensure_attempt_dirs_rejects_a_symlink_before_mutation(tmp_path: Path) -> None:
    host = _started_host(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = host.host_path(HOME_PATH) / "jump"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(EnvironmentFailure, match="symlink"):
        host.ensure_attempt_dirs([f"{HOME_PATH}/jump/planted"])
    assert not (outside / "planted").exists()


def test_ensure_attempt_dirs_leaves_an_unchmodable_dir_and_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    locked = host.host_path(f"{HOME_PATH}/locked")
    locked.mkdir()
    secret = locked / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    secret.chmod(0o600)
    locked.chmod(0o555)
    original = Path.chmod

    def chmod(self: Path, mode: int) -> None:
        if self.name == "locked":
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        original(self, mode)

    monkeypatch.setattr(Path, "chmod", chmod)
    try:
        with pytest.raises(PermissionError):
            host.ensure_attempt_dirs([f"{HOME_PATH}/locked/child"])
        assert not (locked / "child").exists()
        assert stat.S_IMODE(locked.stat().st_mode) == 0o555
        assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    finally:
        original(locked, 0o755)
        original(secret, 0o644)
