"""docker cp and compose cp move collect paths that are not on the bind mount."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.environments.protocol import WORKSPACE_PATH, BoxSpec, EnvironmentFailure, ExecResult
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


@pytest.mark.asyncio
async def test_download_outside_attempt_uses_docker_cp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    calls: list[tuple[list[str], float | None]] = []

    async def fake(args: list[str], *, timeout_sec: float | None) -> ExecResult:
        calls.append((list(args), timeout_sec))
        Path(args[-1]).write_text("dump", encoding="utf-8")
        return ExecResult(0)

    monkeypatch.setattr(host, "_run_docker", fake)
    dest = tmp_path / "out" / "pg.dump"
    await host.download("/tmp/pg.dump", dest)

    assert calls == [(["cp", "ageval-test:/tmp/pg.dump", str(dest)], 600.0)]
    assert dest.read_text(encoding="utf-8") == "dump"


@pytest.mark.asyncio
async def test_sidecar_download_uses_compose_cp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    host._compose_project = "proj"
    host._compose_file = "compose.yaml"
    calls: list[list[str]] = []

    async def fake(args: list[str], *, timeout_sec: float | None) -> ExecResult:
        del timeout_sec
        calls.append(list(args))
        Path(args[-1]).write_text("dump", encoding="utf-8")
        return ExecResult(0)

    monkeypatch.setattr(host, "_run_docker", fake)
    dest = tmp_path / "out" / "pg.dump"
    await host.download("/tmp/pg.dump", dest, service="postgres-db")

    assert calls[0][0] == "compose"
    assert "proj" in calls[0]
    assert "postgres-db:/tmp/pg.dump" in calls[0]
    assert calls[0][-1] == str(dest)


@pytest.mark.asyncio
async def test_traversal_and_missing_compose_do_not_call_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    calls: list[list[str]] = []

    async def fake(args: list[str], *, timeout_sec: float | None) -> ExecResult:
        del timeout_sec
        calls.append(list(args))
        return ExecResult(0)

    monkeypatch.setattr(host, "_run_docker", fake)
    dest = tmp_path / "out"
    with pytest.raises(EnvironmentFailure) as escaped:
        await host.download("/tmp/../etc/passwd", dest)
    assert escaped.value.kind == "environment_path_invalid"
    with pytest.raises(EnvironmentFailure) as missing:
        await host.download("/tmp/pg.dump", dest, service="postgres-db")
    assert missing.value.kind == "environment_capability_missing"
    assert calls == []


@pytest.mark.asyncio
async def test_upload_outside_attempt_uses_docker_cp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)
    calls: list[list[str]] = []

    async def fake(args: list[str], *, timeout_sec: float | None) -> ExecResult:
        del timeout_sec
        calls.append(list(args))
        return ExecResult(0)

    monkeypatch.setattr(host, "_run_docker", fake)
    src = tmp_path / "agent.patch"
    src.write_text("diff", encoding="utf-8")
    await host.upload(src, "/tmp/agent.patch")

    assert calls[0][-3:] == ["mkdir", "-p", "/tmp"]
    assert calls[-1] == ["cp", str(src), "ageval-test:/tmp/agent.patch"]


@pytest.mark.asyncio
async def test_bind_mount_download_does_not_use_docker_cp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _started_host(tmp_path)

    async def fake(args: list[str], *, timeout_sec: float | None) -> ExecResult:
        del args, timeout_sec
        raise AssertionError

    monkeypatch.setattr(host, "_run_docker", fake)

    async def tar_fallback(source: str, dest: Path) -> None:
        raise AssertionError(source)

    monkeypatch.setattr(host, "_download_bind_via_tar", tar_fallback)
    workspace = host.host_path(WORKSPACE_PATH)
    (workspace / "note.txt").write_text("ok", encoding="utf-8")
    dest = tmp_path / "note.txt"
    await host.download(f"{WORKSPACE_PATH}/note.txt", dest)
    assert dest.read_text(encoding="utf-8") == "ok"
