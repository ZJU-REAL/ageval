"""docker tree download copies symlink nodes; does not follow them on the host."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ageval.environments.protocol import (
    ARTIFACTS_PATH,
    WORKSPACE_PATH,
    BoxSpec,
    EnvironmentFailure,
)
from ageval.plugins.contrib.docker.host import DockerHost, _rmtree_force, copy_bind_tree


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


def test_copy_bind_tree_keeps_dangling_venv_link(tmp_path: Path) -> None:
    src = tmp_path / "workspace"
    dest = tmp_path / "snapshot"
    (src / ".venv" / "bin").mkdir(parents=True)
    (src / "out.txt").write_text("ok", encoding="utf-8")
    missing = tmp_path / "no-such-interpreter"
    link = src / ".venv" / "bin" / "python3"
    link.symlink_to(missing)

    copy_bind_tree(src, dest)

    copied = dest / ".venv" / "bin" / "python3"
    assert copied.is_symlink()
    assert copied.readlink() == missing
    assert (dest / "out.txt").read_text(encoding="utf-8") == "ok"


@pytest.mark.asyncio
async def test_download_tree_does_not_error_on_dangling_symlink(tmp_path: Path) -> None:
    host = _started_host(tmp_path)
    workspace = host.host_path(WORKSPACE_PATH)
    (workspace / ".venv" / "bin").mkdir(parents=True)
    (workspace / "script.py").write_text("print(1)\n", encoding="utf-8")
    dangling = workspace / ".venv" / "bin" / "python3"
    dangling.symlink_to(tmp_path / "missing-python")

    dest = tmp_path / "task-artifacts" / "workspace"
    await host.download(WORKSPACE_PATH, dest)

    copied = dest / ".venv" / "bin" / "python3"
    assert copied.is_symlink()
    assert copied.readlink() == tmp_path / "missing-python"
    assert (dest / "script.py").read_text(encoding="utf-8") == "print(1)\n"


@pytest.mark.asyncio
async def test_upload_tree_does_not_error_on_dangling_symlink(tmp_path: Path) -> None:
    host = _started_host(tmp_path)
    staged = tmp_path / "task-artifacts"
    (staged / "workspace" / ".venv" / "bin").mkdir(parents=True)
    (staged / "run-meta.json").write_text("{}", encoding="utf-8")
    dangling = staged / "workspace" / ".venv" / "bin" / "python3"
    dangling.symlink_to(tmp_path / "missing-python")

    await host.upload(staged, ARTIFACTS_PATH)

    copied = host.host_path(ARTIFACTS_PATH) / "workspace" / ".venv" / "bin" / "python3"
    assert copied.is_symlink()
    assert copied.readlink() == tmp_path / "missing-python"


@pytest.mark.asyncio
async def test_download_missing_path_is_environment_failure(tmp_path: Path) -> None:
    host = _started_host(tmp_path)
    with pytest.raises(EnvironmentFailure, match="does not exist"):
        await host.download(f"{WORKSPACE_PATH}/nope.txt", tmp_path / "x")


def test_rmtree_force_removes_readonly_residue(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    objects = dest / ".git" / "objects"
    objects.mkdir(parents=True)
    blob = objects / "pack"
    blob.write_text("old", encoding="utf-8")
    blob.chmod(0o444)
    objects.chmod(0o555)
    (dest / ".git").chmod(0o555)

    _rmtree_force(dest)

    assert not dest.exists()


def test_rmtree_force_unlinks_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)

    _rmtree_force(link)

    assert not link.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def _plant_readonly_residue(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    visible = dest / "visible.txt"
    visible.write_text("old-visible", encoding="utf-8")
    visible.chmod(0o444)
    objects = dest / ".git" / "objects"
    objects.mkdir(parents=True)
    blob = objects / "pack"
    blob.write_text("old-residue", encoding="utf-8")
    blob.chmod(0o444)
    objects.chmod(0o555)
    (dest / ".git").chmod(0o555)


@pytest.mark.asyncio
async def test_unreadable_file_clears_dest_before_tar_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    secret = host.host_path(WORKSPACE_PATH) / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    secret.chmod(0)
    dest = tmp_path / "out" / "secret.txt"
    dest.parent.mkdir()
    dest.write_text("old", encoding="utf-8")
    dest.chmod(0o444)
    seen: list[str] = []

    async def fake(source: str, target: Path) -> None:
        assert not target.exists()
        seen.append(source)
        target.write_text("recovered", encoding="utf-8")

    monkeypatch.setattr(host, "_download_bind_via_tar", fake)
    try:
        await host.download(f"{WORKSPACE_PATH}/secret.txt", dest)
        assert seen == [f"{WORKSPACE_PATH}/secret.txt"]
        assert dest.read_text(encoding="utf-8") == "recovered"
        assert stat.S_IMODE(secret.stat().st_mode) == 0
    finally:
        secret.chmod(0o644)


@pytest.mark.asyncio
async def test_unreadable_child_replaces_directory_dest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    workspace = host.host_path(WORKSPACE_PATH)
    (workspace / "visible.txt").write_text("visible", encoding="utf-8")
    secret = workspace / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    secret.chmod(0)
    dest = tmp_path / "tree"
    _plant_readonly_residue(dest)

    async def fake(source: str, target: Path) -> None:
        assert source == WORKSPACE_PATH
        assert not target.exists()
        target.mkdir()
        (target / "visible.txt").write_text("recovered", encoding="utf-8")

    monkeypatch.setattr(host, "_download_bind_via_tar", fake)
    try:
        await host.download(WORKSPACE_PATH, dest)
        assert (dest / "visible.txt").read_text(encoding="utf-8") == "recovered"
        assert not (dest / ".git").exists()
        assert stat.S_IMODE(secret.stat().st_mode) == 0
    finally:
        secret.chmod(0o644)
