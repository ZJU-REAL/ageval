"""docker tree download copies symlink nodes; does not follow them on the host."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.environments.protocol import (
    ARTIFACTS_PATH,
    WORKSPACE_PATH,
    BoxSpec,
    EnvironmentFailure,
)
from ageval.plugins.contrib.docker.host import DockerHost, copy_bind_tree


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
