"""SSHHost — the ``ssh`` environment kind, in two shapes.

**A, no image:** the Attempt runs directly on the remote machine, under a work
root the box owns. ``attach_stdio`` is ``ssh -T -- <argv>``.

**B, with an image:** the remote machine runs a container from an image that is
already there, and ``attach_stdio`` is ``ssh -- docker exec -i``. Nothing is
built remotely: the operator brought the image.

Either way the Agent runs on the far side, not on the operator's laptop, and the
only local dependency is the ``ssh`` client. There is no vendor SDK here and no
long-lived connection object to leak.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
import shlex
import subprocess
import threading
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.environments.protocol import (
    ARTIFACTS_PATH,
    EVALUATION_PATH,
    HOME_PATH,
    WORKSPACE_PATH,
    BoxSpec,
    EnvironmentCapabilities,
    EnvironmentFailure,
    ExecResult,
    Placement,
    ProbeStatus,
    reject_foreign_service,
)
from ageval.environments.remote_state import (
    CHECKPOINT_SYNC_NAME,
    CHECKPOINT_SYNC_SCRIPT,
    apply_checkpoint_tar,
    parse_state_document,
    push_restored_tree,
    wrapper_line,
)
from ageval.plugins.base import BaseEnvironment
from ageval.plugins.decorators import environment_plugin

BOX_ROOT = "/attempt"
_MAX_STREAM_BYTES = 256 * 1024
_SSH_OPTIONS: tuple[str, ...] = (
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=accept-new",
)


class SSHStdio:
    """Live pipe to a foreground process on the remote side."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.stderr = process.stderr
        self._stderr_tail = ""
        if process.stderr is not None:
            threading.Thread(target=self._drain_stderr, name="ssh-stderr", daemon=True).start()

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            buf = stream.read(4096)
            if not buf:
                break
            if total < _MAX_STREAM_BYTES:
                take = buf[: _MAX_STREAM_BYTES - total]
                chunks.append(take)
                total += len(take)
        self._stderr_tail = b"".join(chunks).decode("utf-8", errors="replace")

    def terminate(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._process.kill()

    def wait(self, timeout: float | None = None) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None


@environment_plugin(priority=100, source="first-party")
class SSHHost(BaseEnvironment):
    """A remote machine, optionally with a container on it."""

    kind = "ssh"
    python_command = ("python3",)
    capabilities = EnvironmentCapabilities(
        exec=True,
        upload=True,
        download=True,
        attach_stdio=True,
        uid_gid=False,
        path_views=False,
        compose=False,
    )

    def __init__(
        self,
        *,
        spec: BoxSpec,
        options: Mapping[str, object] | None = None,
    ) -> None:
        opts = dict(options or {})
        self._host_raw = _required(opts, "host")
        self._user_raw = _text(opts.get("user"))
        self._port_raw = _text(opts.get("port"))
        self._key_env = _text(opts.get("key_env"))
        # Shape B when an image is named; shape A when it is not.
        self._image_raw = _text(opts.get("image"))
        self._host = ""
        self._user: str | None = None
        self._port: str | None = None
        self._image: str | None = None
        self._remote_root = _text(opts.get("root")) or f"/tmp/ageval-{uuid.uuid4().hex[:12]}"
        self._attempt_id = spec.attempt_root.name
        self._container: str | None = None
        self._started = False
        self._stopped = False
        self._attached: list[SSHStdio] = []

    # --- lifecycle -----------------------------------------------------------

    async def preflight(self) -> None:
        """One failure, before anything remote happens."""
        self._host = _expand_option(self._host_raw, field="host") or ""
        self._user = _expand_option(self._user_raw, field="user")
        self._port = _expand_option(self._port_raw, field="port")
        self._image = _expand_option(self._image_raw, field="image")
        if self._key_env is not None and not os.environ.get(self._key_env, "").strip():
            raise EnvironmentFailure(
                "environment_preflight_failed",
                f"{self._key_env} is not set; the ssh kind has no key to use",
            )
        reachable = await self._ssh(["true"], timeout_sec=30.0)
        if reachable.exit_code != 0:
            raise EnvironmentFailure(
                "environment_preflight_failed",
                f"cannot reach {self._host}: {reachable.stderr.strip()[-300:]}",
            )

    async def start(self, *, force_build: bool = False) -> None:
        del force_build  # the operator brought the image; nothing is built here
        if self._started:
            raise EnvironmentFailure("environment_already_started", "ssh box already started")
        made = await self._ssh(["mkdir", "-p", *self._remote_dirs()], timeout_sec=60.0)
        if made.exit_code != 0:
            raise EnvironmentFailure(
                "environment_start_failed",
                f"could not create the remote work root: {made.stderr.strip()[-300:]}",
            )
        if self._image is not None:
            await self._run_remote_container()
        self._started = True

    async def stop(self, *, delete: bool) -> None:
        if self._stopped:
            return
        self._stopped = True
        for pipe in self._attached:
            pipe.terminate()
        self._attached.clear()
        if self._container is not None:
            await self._ssh(["docker", "rm", "-f", self._container], timeout_sec=120.0)
        if delete:
            # Shape A shares the machine with its operator: only our root goes.
            await self._ssh(["rm", "-rf", self._remote_root], timeout_sec=120.0)

    # --- transport -----------------------------------------------------------

    async def exec(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        user: str | None = None,
        service: str | None = None,
        request_id: str | None = None,
    ) -> ExecResult:
        self._assert_started()
        if user is not None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                "ssh does not provide uid_gid; exec(user=…) is unavailable",
            )
        if service is not None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                "ssh does not provide compose; exec(service=…) is unavailable",
            )
        argv = [str(part) for part in command]
        if not argv:
            raise EnvironmentFailure("environment_exec_invalid", "exec requires a command")
        if request_id:
            await self._ensure_sync_script()
            inner = " ".join(shlex.quote(part) for part in argv)
            argv = ["sh", "-c", wrapper_line(request_id, inner)]
        return await self._ssh(
            self._remote_argv(argv, cwd=cwd or WORKSPACE_PATH, env=env),
            timeout_sec=timeout_sec,
        )

    async def upload(self, source: Path, dest: str, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="ssh", verb="upload")
        src = Path(source).expanduser()
        if not src.exists():
            raise EnvironmentFailure(
                "environment_upload_missing",
                f"upload source does not exist: {source}",
            )
        remote = self._remote_path(dest)
        made = await self._ssh(
            ["mkdir", "-p", remote if src.is_dir() else _parent(remote)],
            timeout_sec=60.0,
        )
        if made.exit_code != 0:
            raise EnvironmentFailure(
                "environment_upload_failed",
                f"could not prepare {remote}: {made.stderr.strip()[-300:]}",
            )
        # scp -r src dest/  (when dest exists) nests as dest/src. Copy contents.
        scp_src = f"{src}/." if src.is_dir() else str(src)
        scp_dst = f"{self._target()}:{remote}/" if src.is_dir() else f"{self._target()}:{remote}"
        copied = await self._scp(scp_src, scp_dst, recursive=src.is_dir())
        if copied.exit_code != 0:
            raise EnvironmentFailure(
                "environment_upload_failed",
                f"scp to {remote} failed: {copied.stderr.strip()[-300:]}",
            )
        if self._container is not None:
            await self._ssh(
                ["docker", "cp", f"{remote}/.", f"{self._container}:{dest}"]
                if src.is_dir()
                else ["docker", "cp", remote, f"{self._container}:{dest}"],
                timeout_sec=300.0,
            )

    async def download(self, source: str, dest: Path, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="ssh", verb="download")
        remote = self._remote_path(source)
        if self._container is not None:
            await self._ssh(
                ["docker", "cp", f"{self._container}:{source}", remote],
                timeout_sec=300.0,
            )
        target = Path(dest).expanduser()
        listing = await self._ssh(["test", "-d", remote], timeout_sec=30.0)
        is_dir = listing.exit_code == 0
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
            scp_src, scp_dst = f"{self._target()}:{remote}/.", f"{target}/"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scp_src, scp_dst = f"{self._target()}:{remote}", str(target)
        copied = await self._scp(scp_src, scp_dst, recursive=is_dir)
        if copied.exit_code != 0:
            raise EnvironmentFailure(
                "environment_download_failed",
                f"scp from {remote} failed: {copied.stderr.strip()[-300:]}",
            )

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
    ) -> SSHStdio:
        """Start the process on the far side and hand back its pipes."""
        self._assert_started()
        parts = [str(part) for part in argv]
        if not parts:
            raise EnvironmentFailure("environment_attach_invalid", "attach_stdio requires argv")
        command = [
            "ssh",
            "-T",
            "-o",
            "RequestTTY=no",
            *self._ssh_flags(),
            self._target(),
            "--",
            *self._remote_argv(
                parts,
                cwd=placement.workdir,
                env={"HOME": self.visible_path(placement.home), **dict(env or {})},
            ),
        ]
        process = subprocess.Popen(  # noqa: S603 — argv built here, no shell
            command,
            env=self._client_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pipe = SSHStdio(process)
        self._attached.append(pipe)
        return pipe

    # --- ssh specifics -------------------------------------------------------

    def runtime_handle(self) -> dict[str, object]:
        if not self._host:
            return {}
        return {
            "host": self._host,
            "user": self._user,
            "port": self._port,
            "remote_root": self._remote_root,
            "container_id": self._container,
        }

    async def probe(self, handle: Mapping[str, object]) -> ProbeStatus:
        host = str(handle.get("host") or "").strip()
        root = str(handle.get("remote_root") or "").strip()
        if not host or not root:
            return ProbeStatus(status="absent")
        previous = (self._host, self._user, self._port, self._remote_root, self._container)
        self._host = host
        self._user = str(handle.get("user") or "") or None
        self._port = str(handle.get("port") or "") or None
        self._remote_root = root
        raw_container = handle.get("container_id")
        self._container = str(raw_container) if raw_container else None
        try:
            result = await self._ssh(self._state_argv("dump"), timeout_sec=30.0)
        except Exception:  # noqa: BLE001 — an unreachable host is absent
            result = None
        self._host, self._user, self._port, self._remote_root, self._container = previous
        if result is None or result.exit_code != 0:
            return ProbeStatus(status="absent")
        return parse_state_document(result.stdout)

    async def attach(self, handle: Mapping[str, object]) -> None:
        status = await self.probe(handle)
        if status.status == "absent":
            raise EnvironmentFailure(
                "environment_attach_invalid",
                "ssh environment is not available to attach",
            )
        self._host = str(handle.get("host") or "")
        self._user = str(handle.get("user") or "") or None
        self._port = str(handle.get("port") or "") or None
        self._remote_root = str(handle.get("remote_root") or "")
        raw_container = handle.get("container_id")
        self._container = str(raw_container) if raw_container else None
        self._started = True
        self._stopped = False

    async def push_restored_box(self, box: Path) -> None:
        await push_restored_tree(self, box)

    def sync_box_state(self, box: Path) -> None:
        if not self._started:
            return
        _drive(self._sync_box_state(box))

    async def _sync_box_state(self, box: Path) -> None:
        from ageval.environments.remote_state import local_state_files

        await self._ensure_sync_script()
        for path, remote in local_state_files(box):
            await self.upload(path, remote)

    def mirror_checkpoint(self, dest: Path) -> None:
        if not self._started:
            return
        _drive(self._pull_checkpoint(dest))

    async def _pull_checkpoint(self, dest: Path) -> None:
        out = "/tmp/.ageval-state/delta.tar"
        packed = await self._ssh(self._state_argv("pack", out), timeout_sec=120.0)
        if packed.exit_code != 0:
            return
        local = dest / "delta.tar"
        local.parent.mkdir(parents=True, exist_ok=True)
        fetched = await self._scp(f"{self._target()}:{out}", str(local), recursive=False)
        if fetched.exit_code != 0 or not local.is_file():
            return
        apply_checkpoint_tar(dest, local.read_bytes())
        local.unlink()

    async def _ensure_sync_script(self) -> None:
        remote = "/tmp/.ageval-state"
        made = await self._ssh(["mkdir", "-p", remote], timeout_sec=30.0)
        if made.exit_code != 0:
            raise EnvironmentFailure(
                "environment_setup_failed",
                "could not create the remote state directory",
            )
        import tempfile

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(CHECKPOINT_SYNC_SCRIPT)
            path = Path(handle.name)
        try:
            copied = await self._scp(
                str(path),
                f"{self._target()}:{remote}/{CHECKPOINT_SYNC_NAME}",
                recursive=False,
            )
        finally:
            path.unlink(missing_ok=True)
        if copied.exit_code != 0:
            raise EnvironmentFailure(
                "environment_setup_failed",
                "could not upload checkpoint_sync.py",
            )
        if not self._container:
            return
        made_in = await self._ssh(
            ["docker", "exec", self._container, "mkdir", "-p", remote],
            timeout_sec=30.0,
        )
        if made_in.exit_code != 0:
            raise EnvironmentFailure(
                "environment_setup_failed",
                "could not create the container state directory",
            )
        placed = await self._ssh(
            [
                "docker",
                "cp",
                f"{remote}/{CHECKPOINT_SYNC_NAME}",
                f"{self._container}:{remote}/{CHECKPOINT_SYNC_NAME}",
            ],
            timeout_sec=30.0,
        )
        if placed.exit_code != 0:
            raise EnvironmentFailure(
                "environment_setup_failed",
                "could not copy checkpoint_sync.py into the container",
            )

    def _state_argv(self, *args: str) -> list[str]:
        inner = ["python3", f"/tmp/.ageval-state/{CHECKPOINT_SYNC_NAME}", *args]
        if self._container:
            return ["docker", "exec", self._container, *inner]
        return inner

    def placement(self) -> Placement:
        if not self._started:
            raise EnvironmentFailure("environment_not_started", "ssh box is not started")
        return Placement(
            target_id=self._container or f"ssh:{self._host}",
            user=None,
            workdir=WORKSPACE_PATH,
            home=HOME_PATH,
        )

    def visible_path(self, box_path: str) -> str:
        """Shape B owns ``/attempt``; shape A maps it under the remote root."""
        if self._container is not None:
            return box_path
        return self._remote_path(box_path)

    def _remote_path(self, box_path: str) -> str:
        text = str(box_path or "").strip()
        if not text.startswith(BOX_ROOT):
            raise EnvironmentFailure(
                "environment_path_invalid",
                f"box paths must start with {BOX_ROOT}/: {box_path!r}",
            )
        rel = text[len(BOX_ROOT) :].lstrip("/")
        if ".." in Path(rel).parts:
            raise EnvironmentFailure(
                "environment_path_invalid",
                f"box path escapes the work root: {box_path!r}",
            )
        return f"{self._remote_root}/{rel}" if rel else self._remote_root

    def _remote_dirs(self) -> list[str]:
        return [self._remote_path(p) for p in (WORKSPACE_PATH, HOME_PATH, ARTIFACTS_PATH)]

    def _remote_argv(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None,
    ) -> list[str]:
        """Wrap argv for whichever shape this box is."""
        exported = self._box_env(env)
        if self._container is not None:
            flags: list[str] = []
            for key, value in exported.items():
                flags.extend(["-e", f"{key}={value}"])
            return ["docker", "exec", "-i", "-w", cwd, *flags, self._container, *argv]
        # OpenSSH joins argv after ``--`` with spaces into one shell -c string.
        # Nested ``sh -c mkdir -p …`` would then run as ``sh -c mkdir``. One
        # shlex-joined argument keeps env -C, assignments, and the command intact.
        parts: list[str] = ["env", "-C", self._remote_path(cwd)]
        for key, value in exported.items():
            parts.append(f"{key}={value}")
        parts.extend(str(part) for part in argv)
        # ``exec`` so the login shell is replaced and stdin stays on the entry.
        return ["exec " + shlex.join(parts)]

    def _box_env(self, env: Mapping[str, str] | None) -> dict[str, str]:
        """Caller env plus this box's own path publication."""
        out = {str(k): str(v) for k, v in (env or {}).items() if v}
        for name, path in (
            ("AGEVAL_WORKSPACE", WORKSPACE_PATH),
            ("AGEVAL_ARTIFACTS", ARTIFACTS_PATH),
            ("AGEVAL_EVALUATION", EVALUATION_PATH),
        ):
            out.setdefault(name, self.visible_path(path))
        return out

    async def _run_remote_container(self) -> None:
        name = f"ageval-{uuid.uuid4().hex[:12]}"
        started = await self._ssh(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-v",
                f"{self._remote_root}:{BOX_ROOT}",
                "-w",
                WORKSPACE_PATH,
                "--entrypoint",
                "sh",
                str(self._image),
                "-c",
                "while :; do sleep 3600; done",
            ],
            timeout_sec=300.0,
        )
        if started.exit_code != 0:
            raise EnvironmentFailure(
                "environment_start_failed",
                f"remote docker run failed: {started.stderr.strip()[-300:]}",
            )
        self._container = started.stdout.strip() or name

    def _target(self) -> str:
        return f"{self._user}@{self._host}" if self._user else self._host

    def _ssh_flags(self) -> list[str]:
        flags = list(_SSH_OPTIONS)
        if self._port:
            flags.extend(["-p", self._port])
        key = os.environ.get(self._key_env or "", "").strip()
        if key:
            flags.extend(["-i", key])
        return flags

    def _scp_flags(self) -> list[str]:
        flags = list(_SSH_OPTIONS)
        if self._port:
            flags.extend(["-P", self._port])
        key = os.environ.get(self._key_env or "", "").strip()
        if key:
            flags.extend(["-i", key])
        return flags

    def _client_env(self) -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", ""),
        }

    async def _ssh(self, argv: Sequence[str], *, timeout_sec: float | None) -> ExecResult:
        return await self._run(
            ["ssh", "-T", *self._ssh_flags(), self._target(), "--", *argv],
            timeout_sec=timeout_sec,
        )

    async def _scp(self, source: str, dest: str, *, recursive: bool) -> ExecResult:
        argv = ["scp", *self._scp_flags()]
        if recursive:
            argv.append("-r")
        return await self._run([*argv, source, dest], timeout_sec=600.0)

    async def _run(self, argv: Sequence[str], *, timeout_sec: float | None) -> ExecResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=self._client_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            return ExecResult(exit_code=124, stderr="remote command timed out")
        return ExecResult(
            exit_code=int(process.returncode or 0),
            stdout=stdout[:_MAX_STREAM_BYTES].decode("utf-8", errors="replace"),
            stderr=stderr[:_MAX_STREAM_BYTES].decode("utf-8", errors="replace"),
        )

    def _assert_started(self) -> None:
        if not self._started:
            raise EnvironmentFailure("environment_not_started", "ssh box is not started")
        if self._stopped:
            raise EnvironmentFailure("environment_stopped", "ssh box is already stopped")


def _drive(coro: Any) -> Any:
    """Run SSH I/O from ``capture_box``, which already sits on the Attempt loop.

    ``asyncio.run`` on that loop raises ``RuntimeError``. A live loop therefore
    gets a worker thread and its own loop; a sync caller still uses ``asyncio.run``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _expand_option(raw: str | None, *, field: str) -> str | None:
    """``${NAME}`` in host/user/port/image is a locator, resolved at preflight."""
    if raw is None:
        return None
    text = raw.strip()
    if text.startswith("${") and text.endswith("}") and len(text) > 3:
        name = text[2:-1]
        value = os.environ.get(name, "").strip()
        if not value:
            raise EnvironmentFailure(
                "environment_preflight_failed",
                f"{name} is not set; ssh {field} has no value",
            )
        return value
    return text


def _required(options: Mapping[str, object], key: str) -> str:
    value = _text(options.get(key))
    if value is None:
        raise EnvironmentFailure(
            "environment_options_invalid",
            f"the ssh kind needs environment options: {key}",
        )
    return value


def _parent(remote_path: str) -> str:
    head, _, _ = remote_path.rpartition("/")
    return head or "/"


def _text(raw: object) -> str | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


__all__ = ["SSHHost", "SSHStdio"]
