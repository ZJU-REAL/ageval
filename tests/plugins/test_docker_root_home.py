"""Real Docker: host-created HOME stays writable; root-owned dirs use docker cp.

Docker Desktop on macOS remaps container root onto the host uid, so the
permission fallback cannot be observed here. That case skips. Linux, where
the bind mount keeps uid 0, runs it.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from ageval.environments.protocol import HOME_PATH, WORKSPACE_PATH, BoxSpec
from ageval.evidence.checkpoints import CheckpointStore
from ageval.plugins.contrib.acp.home import prepare_home, write_lock_overlays
from ageval.plugins.contrib.acp.lock_overlay import OverlayFile
from ageval.plugins.contrib.acp.registry import get_entry
from ageval.plugins.contrib.docker.host import DockerHost
from ageval.plugins.contrib.docker.images import daemon_available


def _skip_reason() -> str:
    if os.environ.get("AGEVAL_SKIP_DOCKER") == "1":
        return "AGEVAL_SKIP_DOCKER=1"
    if os.geteuid() == 0:
        return "a root test runner masks permission failures"
    if not daemon_available():
        return "docker daemon is not available"
    return ""


_SKIP = _skip_reason()
pytestmark = pytest.mark.skipif(bool(_SKIP), reason=_SKIP or "docker")


def _host(tmp_path: Path, *, user: str | None) -> DockerHost:
    options: dict[str, str] = {"image": "alpine:3.20"}
    if user is not None:
        options["user"] = user
    return DockerHost(
        spec=BoxSpec(
            attempt_root=tmp_path / "box",
            task_root=tmp_path,
            repo_root=tmp_path,
        ),
        options=options,
    )


async def _started(tmp_path: Path, *, user: str | None) -> DockerHost:
    host = _host(tmp_path, user=user)
    await host.start()
    return host


@pytest.mark.asyncio
@pytest.mark.parametrize("user", ["root", None])
async def test_prepare_home_and_overlays_on_a_real_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, user: str | None
) -> None:
    monkeypatch.setattr(
        "ageval.plugins.contrib.acp.home.Path.home", lambda: tmp_path / "empty-home"
    )
    host = await _started(tmp_path, user=user)
    try:
        pi = get_entry("pi")
        opencode = get_entry("opencode")
        assert pi is not None
        assert opencode is not None
        await prepare_home(host, pi)
        await prepare_home(host, opencode)
        written = await write_lock_overlays(
            host,
            [
                OverlayFile(
                    dest=".pi/agent/models.json",
                    payload={"providers": {"demo": {"id": "demo"}}},
                    kind="json",
                ),
                OverlayFile(
                    dest=".config/opencode/opencode.json",
                    payload={"provider": {"id": "demo"}},
                    kind="json",
                ),
            ],
        )
        assert ".pi/agent/models.json" in written
        assert ".config/opencode/opencode.json" in written
        home = host.host_path(HOME_PATH)
        for rel in (".pi", ".pi/agent", ".config", ".config/opencode", ".local/share/opencode"):
            path = home / rel
            assert path.is_dir()
            assert stat.S_IMODE(path.stat().st_mode) == 0o777
            assert path.stat().st_uid == os.geteuid()
        models = json.loads((home / ".pi/agent/models.json").read_text(encoding="utf-8"))
        assert models["providers"]["demo"]["id"] == "demo"
        opened = json.loads((home / ".config/opencode/opencode.json").read_text(encoding="utf-8"))
        assert opened["provider"]["id"] == "demo"
        listed = await host.exec(["cat", f"{HOME_PATH}/.pi/agent/models.json"])
        assert listed.exit_code == 0
        assert "demo" in listed.stdout
    finally:
        await host.stop(delete=True)


@pytest.mark.asyncio
async def test_root_owned_upload_and_checkpoint_when_the_host_cannot_read(
    tmp_path: Path,
) -> None:
    host = await _started(tmp_path, user="root")
    try:
        script = (
            "mkdir -p /attempt/home/planted && chmod 755 /attempt/home/planted "
            "&& echo old > /attempt/home/planted/secret.json "
            "&& chmod 600 /attempt/home/planted/secret.json"
        )
        planted = await host.exec(["sh", "-c", script])
        assert planted.exit_code == 0
        secret = host.host_path(f"{HOME_PATH}/planted/secret.json")
        try:
            secret.read_bytes()
        except PermissionError:
            host_blocked = True
        else:
            host_blocked = False
        if not host_blocked:
            pytest.skip(
                "bind mount remaps container root onto the host uid; "
                "permission fallback is covered by unit tests"
            )
        note = host.host_path(f"{WORKSPACE_PATH}/note.txt")
        note.write_text("kept", encoding="utf-8")
        src = tmp_path / "models.json"
        src.write_text('{"ok": true}\n', encoding="utf-8")
        await host.upload(src, f"{HOME_PATH}/planted/models.json")
        replacement = tmp_path / "secret.json"
        replacement.write_text('{"replaced": true}\n', encoding="utf-8")
        await host.upload(replacement, f"{HOME_PATH}/planted/secret.json")
        models = await host.exec(["cat", f"{HOME_PATH}/planted/models.json"])
        replaced = await host.exec(["cat", f"{HOME_PATH}/planted/secret.json"])
        assert models.exit_code == 0
        assert '"ok": true' in models.stdout
        assert replaced.exit_code == 0
        assert "replaced" in replaced.stdout
        # Re-plant a private file. The upload above replaced secret.json.
        again = await host.exec(
            [
                "sh",
                "-c",
                "echo hidden > /attempt/home/planted/hidden.txt"
                " && chmod 600 /attempt/home/planted/hidden.txt",
            ]
        )
        assert again.exit_code == 0
        hidden = host.host_path(f"{HOME_PATH}/planted/hidden.txt")
        hidden_mode = hidden.stat().st_mode
        hidden_uid = hidden.stat().st_uid
        store = CheckpointStore(tmp_path / "evidence", host.root)
        manifest = json.loads(store.capture(1).read_text(encoding="utf-8"))
        entries = manifest["entries"]
        assert "workspace/note.txt" in entries
        assert "home/planted/hidden.txt" not in entries
        assert hidden.stat().st_mode == hidden_mode
        assert hidden.stat().st_uid == hidden_uid
    finally:
        await host.stop(delete=True)
