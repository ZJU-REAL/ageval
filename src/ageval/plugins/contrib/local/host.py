"""LocalHost — the ``local`` environment kind backed by a real directory tree."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from ageval.environments.box_state import (
    host_pid_alive,
    host_state_dir,
    probe_box,
    write_inflight,
    write_last_exit,
)
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
from ageval.plugins.base import BaseEnvironment
from ageval.plugins.decorators import environment_plugin

_BOX_ROOT = "/attempt"
_MAX_STREAM_BYTES = 256 * 1024


def _finish_exec(box: Path, request_id: str | None, result: ExecResult) -> None:
    if not request_id:
        return
    from ageval.environments.box_state import INFLIGHT_OUTPUT_NAME, ensure_state_dir

    folder = ensure_state_dir(box)
    (folder / INFLIGHT_OUTPUT_NAME).write_text(
        f"{result.stdout}{result.stderr}",
        encoding="utf-8",
    )
    write_last_exit(
        box,
        {
            "request_id": request_id,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )


class LocalStdio:
    """Live pipe to a foreground process started inside the local box."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.stderr = process.stderr

    @property
    def pid(self) -> int:
        return self._process.pid

    def terminate(self) -> None:
        if self._process.poll() is not None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None


@environment_plugin(priority=100, source="first-party")
class LocalHost(BaseEnvironment):
    """Real local box: one work root per Attempt, real subprocesses."""

    kind = "local"
    # The box is this interpreter's own machine, so it is also its Python.
    python_command = (sys.executable,)
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
        del options  # local takes no job options and builds no image
        self._root = spec.attempt_root.expanduser().resolve(strict=False)
        self._started = False
        self._stopped = False
        self.reattached = False
        self._attached: list[LocalStdio] = []

    # --- lifecycle -----------------------------------------------------------

    async def preflight(self) -> None:
        parent = self._root.parent
        parent.mkdir(parents=True, exist_ok=True)
        if not os.access(parent, os.W_OK):
            raise EnvironmentFailure(
                "environment_preflight_failed",
                f"local work root is not writable: {parent}",
            )

    async def start(self, *, force_build: bool = False) -> None:
        del force_build  # local has no image to build
        if self._started:
            raise EnvironmentFailure("environment_already_started", "local box already started")
        for rel in ("workspace", "home", "artifacts"):
            (self._root / rel).mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._started = True
        self.reattached = False

    async def stop(self, *, delete: bool) -> None:
        if self._stopped:
            return
        self._stopped = True
        for pipe in self._attached:
            pipe.terminate()
        self._attached.clear()
        if delete and self._root.is_dir():
            shutil.rmtree(self._root, ignore_errors=True)

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
                "local kind does not provide uid_gid; exec(user=…) is unavailable",
            )
        if service is not None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                "local kind does not provide compose; exec(service=…) is unavailable",
            )
        argv = [str(part) for part in command]
        if not argv:
            raise EnvironmentFailure("environment_exec_invalid", "exec requires a command")
        workdir = self.host_path(cwd or WORKSPACE_PATH)
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workdir),
            env=self._child_env(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if request_id:
            write_inflight(self.state_root, pid=process.pid, request_id=request_id)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            self._kill_group(process.pid)
            with contextlib.suppress(OSError):
                await process.wait()
            result = ExecResult(exit_code=124, stdout="", stderr="exec timed out", truncated=False)
            _finish_exec(self.state_root, request_id, result)
            return result
        truncated = len(stdout) > _MAX_STREAM_BYTES or len(stderr) > _MAX_STREAM_BYTES
        result = ExecResult(
            exit_code=int(process.returncode or 0),
            stdout=stdout[:_MAX_STREAM_BYTES].decode("utf-8", errors="replace"),
            stderr=stderr[:_MAX_STREAM_BYTES].decode("utf-8", errors="replace"),
            truncated=truncated,
        )
        _finish_exec(self.state_root, request_id, result)
        return result

    async def upload(self, source: Path, dest: str, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="local kind", verb="upload")
        src = Path(source).expanduser()
        if not src.exists():
            raise EnvironmentFailure(
                "environment_upload_missing",
                f"upload source does not exist: {source}",
            )
        target = self.host_path(dest)
        if src.is_dir():
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, target)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    async def download(self, source: str, dest: Path, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="local kind", verb="download")
        src = self.host_path(source)
        if not src.exists():
            raise EnvironmentFailure(
                "environment_download_missing",
                f"download source does not exist in box: {source}",
            )
        target = Path(dest).expanduser()
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, target, dirs_exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
    ) -> LocalStdio:
        """Start a foreground process in the open box and hand back its pipes."""
        self._assert_started()
        parts = [str(part) for part in argv]
        if not parts:
            raise EnvironmentFailure("environment_attach_invalid", "attach_stdio requires argv")
        child_env = self._child_env(env)
        child_env.setdefault("HOME", self.visible_path(placement.home))
        process = subprocess.Popen(  # noqa: S603 — argv comes from the entry registry
            parts,
            cwd=self.visible_path(placement.workdir),
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        pipe = LocalStdio(process)
        self._attached.append(pipe)
        return pipe

    # --- local specifics -----------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def state_root(self) -> Path:
        return host_state_dir(self._root)

    def runtime_handle(self) -> dict[str, object]:
        return {"kind": "local"}

    async def probe(self, handle: Mapping[str, object]) -> ProbeStatus:
        del handle
        if not self._root.is_dir():
            return ProbeStatus(status="absent")
        return probe_box(self._root, pid_alive=host_pid_alive, state=self.state_root)

    async def attach(self, handle: Mapping[str, object]) -> None:
        del handle
        if not self._root.is_dir():
            msg = "local box directory is absent"
            raise EnvironmentFailure("environment_absent", msg)
        for rel in ("workspace", "home", "artifacts"):
            (self._root / rel).mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._started = True
        self._stopped = False
        self.reattached = True

    def placement(self) -> Placement:
        """Attach facts for this box. ``target_id`` is opaque above the kind."""
        return Placement(
            target_id=f"local:{self.root.name}",
            user=None,
            workdir=WORKSPACE_PATH,
            home=HOME_PATH,
        )

    def visible_path(self, box_path: str) -> str:
        """In-box path as this machine's processes see it."""
        return str(self.host_path(box_path))

    def host_path(self, box_path: str) -> Path:
        """Map an in-box path onto this work root; reject anything outside."""
        text = str(box_path or "").strip()
        if not text:
            raise EnvironmentFailure("environment_path_invalid", "empty box path")
        if not text.startswith(_BOX_ROOT):
            raise EnvironmentFailure(
                "environment_path_invalid",
                f"box paths must start with {_BOX_ROOT}/: {box_path!r}",
            )
        rel = text[len(_BOX_ROOT) :].lstrip("/")
        if ".." in Path(rel).parts:
            raise EnvironmentFailure(
                "environment_path_invalid",
                f"box path escapes the work root: {box_path!r}",
            )
        return (self.root / rel) if rel else self.root

    def _child_env(self, env: Mapping[str, str] | None) -> dict[str, str]:
        """Only what the caller declared, plus this box's own path publication.

        A kind publishes the paths *as its processes see them*; here the box is
        a host directory, so the in-box contract maps onto real host paths.
        """
        out = {str(k): str(v) for k, v in (env or {}).items()}
        out.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
        out.setdefault("LANG", os.environ.get("LANG", "C"))
        out.setdefault("AGEVAL_WORKSPACE", self.visible_path(WORKSPACE_PATH))
        out.setdefault("AGEVAL_ARTIFACTS", self.visible_path(ARTIFACTS_PATH))
        out.setdefault("AGEVAL_EVALUATION", self.visible_path(EVALUATION_PATH))
        return out

    def _assert_started(self) -> None:
        if not self._started:
            raise EnvironmentFailure(
                "environment_not_started",
                "local box is not started",
            )
        if self._stopped:
            raise EnvironmentFailure("environment_stopped", "local box is already stopped")

    @staticmethod
    def _kill_group(pid: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)


__all__ = ["EVALUATION_PATH", "LocalHost", "LocalStdio"]
