"""Root-owned private files on the /attempt bind mount still download."""

from __future__ import annotations

import os
import stat
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from ageval.environments.protocol import WORKSPACE_PATH, BoxSpec
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.docker.images import daemon_available

_IMAGE = "alpine:3.20"
_RELATIVE = (
    "secret.txt",
    "private",
    "private/inner.txt",
    ".git",
    ".git/objects",
    ".git/objects/pack",
    "visible.txt",
    ".venv/bin/python3",
)
_SEED = """
set -eu
mkdir -p /attempt/workspace/private /attempt/workspace/.venv/bin /attempt/workspace/.git/objects
printf secret-body > /attempt/workspace/secret.txt
chmod 0600 /attempt/workspace/secret.txt
printf inner-body > /attempt/workspace/private/inner.txt
chmod 0600 /attempt/workspace/private/inner.txt
chmod 0700 /attempt/workspace/private
ln -s /usr/bin/python3 /attempt/workspace/.venv/bin/python3
printf from-container > /attempt/workspace/.git/objects/pack
chmod 0444 /attempt/workspace/.git/objects/pack
chmod 0555 /attempt/workspace/.git/objects
chmod 0555 /attempt/workspace/.git
printf visible > /attempt/workspace/visible.txt
chmod 0644 /attempt/workspace/visible.txt
"""


def _skip_without_docker() -> None:
    if os.geteuid() == 0:
        pytest.skip("private-file fallback is for a non-root host user")
    if os.environ.get("AGEVAL_SKIP_DOCKER") == "1":
        pytest.skip("AGEVAL_SKIP_DOCKER=1")
    if not daemon_available():
        pytest.skip("docker daemon is not reachable")


def _docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _guard_source_chmod(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    real = os.chmod
    resolved_root = root.resolve()

    def guarded(
        path: str | os.PathLike[str],
        mode: int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        resolved = Path(path).resolve()
        assert resolved != resolved_root and resolved_root not in resolved.parents, path
        real(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "chmod", guarded)


def _mount_modes(workspace: Path) -> dict[str, int | None]:
    found: dict[str, int | None] = {}
    for rel in _RELATIVE:
        path = workspace / rel
        try:
            found[rel] = stat.S_IMODE(path.lstat().st_mode)
        except PermissionError:
            found[rel] = None
    return found


def _plant_residue(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    visible = dest / "visible.txt"
    visible.write_text("old-visible", encoding="utf-8")
    visible.chmod(0o444)
    objects = dest / ".git" / "objects"
    objects.mkdir(parents=True)
    pack = objects / "pack"
    pack.write_text("old-residue", encoding="utf-8")
    pack.chmod(0o444)
    objects.chmod(0o555)
    (dest / ".git").chmod(0o555)


def _assert_tree(dest: Path) -> None:
    assert (dest / "secret.txt").read_text(encoding="utf-8") == "secret-body"
    assert (dest / "private" / "inner.txt").read_text(encoding="utf-8") == "inner-body"
    assert (dest / "visible.txt").read_text(encoding="utf-8") == "visible"
    assert (dest / ".git" / "objects" / "pack").read_text(encoding="utf-8") == "from-container"
    link = dest / ".venv" / "bin" / "python3"
    assert link.is_symlink()
    assert os.readlink(link) == "/usr/bin/python3"
    assert (dest / "secret.txt").stat().st_uid == os.getuid()
    assert (dest / "private" / "inner.txt").stat().st_uid == os.getuid()


@pytest.fixture
def root_attempt(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    _skip_without_docker()
    bind = tmp_path / "attempt"
    bind.mkdir()
    name = f"ageval-dl-{uuid.uuid4().hex[:10]}"
    started = _docker(
        "run",
        "-d",
        "--name",
        name,
        "--user",
        "0",
        "-v",
        f"{bind}:/attempt",
        _IMAGE,
        "sleep",
        "3600",
    )
    assert started.returncode == 0, started.stderr
    try:
        seeded = _docker("exec", name, "sh", "-c", _SEED)
        assert seeded.returncode == 0, seeded.stderr
        yield name, bind
    finally:
        _docker("rm", "-f", name, timeout=30)


def _host(bind: Path, container: str, tmp_path: Path) -> DockerHost:
    spec = BoxSpec(attempt_root=bind, task_root=tmp_path, repo_root=tmp_path)
    host = DockerHost(spec=spec)
    host._started = True
    host._container = container
    return host


@pytest.mark.asyncio
async def test_private_bind_download_while_running(
    tmp_path: Path,
    root_attempt: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name, bind = root_attempt
    host = _host(bind, name, tmp_path)
    workspace = bind / "workspace"
    before = _mount_modes(workspace)
    _guard_source_chmod(monkeypatch, bind)

    secret_dest = tmp_path / "secret.txt"
    await host.download(f"{WORKSPACE_PATH}/secret.txt", secret_dest)
    assert secret_dest.read_text(encoding="utf-8") == "secret-body"
    assert secret_dest.stat().st_uid == os.getuid()

    tree = tmp_path / "tree"
    await host.download(WORKSPACE_PATH, tree)
    _assert_tree(tree)
    assert _mount_modes(workspace) == before

    # 0444 / 0555 residue makes the host copy fail and forces the docker cp
    # replacement, including on Docker Desktop where bind files are host-owned.
    residue = tmp_path / "residue"
    _plant_residue(residue)
    stale = residue / "secret.txt"
    stale.write_text("old-secret", encoding="utf-8")
    stale.chmod(0o444)
    await host.download(WORKSPACE_PATH, residue)
    _assert_tree(residue)
    assert (residue / "secret.txt").read_text(encoding="utf-8") == "secret-body"
    assert _mount_modes(workspace) == before


@pytest.mark.asyncio
async def test_private_bind_download_after_stop(
    tmp_path: Path,
    root_attempt: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name, bind = root_attempt
    host = _host(bind, name, tmp_path)
    workspace = bind / "workspace"
    before = _mount_modes(workspace)
    stopped = _docker("stop", name, timeout=60)
    assert stopped.returncode == 0, stopped.stderr
    _guard_source_chmod(monkeypatch, bind)

    secret_dest = tmp_path / "secret.txt"
    secret_dest.write_text("old-secret", encoding="utf-8")
    secret_dest.chmod(0o444)
    await host.download(f"{WORKSPACE_PATH}/secret.txt", secret_dest)
    assert secret_dest.read_text(encoding="utf-8") == "secret-body"
    assert secret_dest.stat().st_uid == os.getuid()

    residue = tmp_path / "residue"
    _plant_residue(residue)
    await host.download(WORKSPACE_PATH, residue)
    _assert_tree(residue)
    assert _mount_modes(workspace) == before
