"""DockerHost — the ``docker`` environment kind.

Everything docker-shaped lives in this file: the container id, the ``docker
exec`` argv, the uid/gid, the compose calls, and the rule that the daemon's own
locator variables must never reach a process inside the box. Above it, the ACP
executor and the Attempt phases see only the environment Protocol.

Files move through a bind mount: the Attempt work root is the container's
``/attempt``, so an upload is a copy on this side and a read is a read on that
side. ``/attempt/evaluation`` therefore appears exactly when the evaluate phase
uploads it, and not one moment earlier.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

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
)
from ageval.plugins.contrib.docker.images import (
    daemon_available,
    docker,
    host_platform,
    resolve_image,
)

BOX_ROOT = "/attempt"
ATTEMPT_UID = 10001
ATTEMPT_GID = 10001
_MAX_STREAM_BYTES = 256 * 1024
_PYTHON_VERSION_RE = re.compile(r"^\d+\.\d+$")

# The daemon locators the docker CLI itself needs. They describe *this* machine,
# so they must never be projected into a container.
_DAEMON_ENV_KEYS = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
    "SSL_CERT_FILE",
)


class DockerStdio:
    """Live pipe to a ``docker exec -i`` process."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.stderr = process.stderr

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


class DockerHost:
    """A long-lived container per Attempt, driven by the docker CLI."""

    kind = "docker"
    python_command = ("python3",)
    capabilities = EnvironmentCapabilities(
        exec=True,
        upload=True,
        download=True,
        attach_stdio=True,
        uid_gid=True,
        path_views=True,
        compose=True,
    )

    def __init__(
        self,
        *,
        spec: BoxSpec,
        options: Mapping[str, object] | None = None,
        plugin_layers: Sequence[tuple[str, str, str, str]] = (),
    ) -> None:
        opts = dict(options or {})
        self._plugin_layers = tuple(plugin_layers)
        self._root = spec.attempt_root.expanduser().resolve(strict=False)
        self._task_root = spec.task_root.resolve(strict=False)
        self._repo_root = spec.repo_root.resolve(strict=False)
        self._dockerfile = spec.dockerfile
        self._compose_file = spec.compose_file
        self._declared_image = _text(opts.get("image") or opts.get("docker_image"))
        self._platform = _text(opts.get("platform")) or host_platform()
        # The Agent runs inside the box and has to reach its provider.
        self._network = _text(opts.get("network")) or "bridge"
        self._user = _box_user(opts.get("user"))
        self._python_version = _box_python_version(opts.get("python_version"))
        self._egress = _text(opts.get("egress"))
        raw_allow = opts.get("egress_allowlist") or ()
        if isinstance(raw_allow, (list, tuple)):
            self._egress_allowlist = tuple(str(item) for item in raw_allow if str(item).strip())
        else:
            self._egress_allowlist = ()
        self._proxy: object | None = None
        self._proxy_url: str | None = None
        self._container: str | None = None
        self._compose_project: str | None = None
        self._image: str | None = None
        self._started = False
        self._stopped = False
        self._attached: list[DockerStdio] = []

    # --- lifecycle -----------------------------------------------------------

    async def preflight(self) -> None:
        if not daemon_available():
            raise EnvironmentFailure(
                "environment_preflight_failed",
                "the docker daemon is not reachable from this machine",
            )
        self._root.parent.mkdir(parents=True, exist_ok=True)

    async def start(self, *, force_build: bool = False) -> None:
        if self._started:
            raise EnvironmentFailure("environment_already_started", "docker box already started")
        self._prepare_work_root()
        tag, _digest = resolve_image(
            task_root=self._task_root or self._repo_root,
            dockerfile_rel=self._dockerfile,
            declared_image=self._declared_image,
            platform=self._platform,
            force_build=force_build,
            plugin_layers=self._plugin_layers,
            python_version=self._python_version,
        )
        self._image = tag
        # Sidecars come up first: the Attempt container joins their network, so
        # a service is reachable by name and nothing needs an orchestrator.
        network = self._network
        if self._compose_file is not None:
            self._compose_up()
            network = f"{self._compose_project}_default"
        name = f"ageval-{uuid.uuid4().hex[:12]}"
        extra_run = self._start_egress_proxy()
        started = docker(
            "run",
            "-d",
            "--name",
            name,
            "--user",
            self._user,
            "--security-opt",
            "no-new-privileges",
            "--network",
            network,
            *extra_run,
            *self._volume_flags(),
            "-w",
            WORKSPACE_PATH,
            "--entrypoint",
            "sh",
            tag,
            "-c",
            "while :; do sleep 3600; done",
        )
        if started.returncode != 0:
            self._stop_egress_proxy()
            raise EnvironmentFailure(
                "environment_start_failed",
                f"docker run failed: {(started.stderr or started.stdout).strip()[-500:]}",
            )
        self._container = (started.stdout or "").strip() or name
        self._started = True

    async def stop(self, *, delete: bool) -> None:
        if self._stopped:
            return
        self._stopped = True
        for pipe in self._attached:
            pipe.terminate()
        self._attached.clear()
        self._stop_egress_proxy()
        if self._compose_project is not None:
            self._compose("down", "-v")
        if self._container is not None:
            docker("rm", "-f", self._container, timeout=120.0)
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
    ) -> ExecResult:
        self._assert_started()
        argv = [str(part) for part in command]
        if not argv:
            raise EnvironmentFailure("environment_exec_invalid", "exec requires a command")
        if service is not None:
            return await self._compose_exec(service, argv, timeout_sec=timeout_sec)
        assert self._container is not None
        prefix = [
            "exec",
            "-u",
            user or self._user,
            "-w",
            cwd or WORKSPACE_PATH,
            *self._env_flags(env),
            self._container,
        ]
        return await self._run_docker(prefix + argv, timeout_sec=timeout_sec)

    async def upload(self, source: Path, dest: str) -> None:
        """Copy into the bind-mounted work root; the container sees it at once."""
        self._assert_started()
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
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        _make_box_writable(target)

    async def download(self, source: str, dest: Path) -> None:
        self._assert_started()
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
    ) -> DockerStdio:
        """Start a foreground process in the container and hand back its pipes."""
        self._assert_started()
        parts = [str(part) for part in argv]
        if not parts:
            raise EnvironmentFailure("environment_attach_invalid", "attach_stdio requires argv")
        assert self._container is not None
        command = [
            "docker",
            "exec",
            "-i",
            "-u",
            placement.user or self._user,
            "-w",
            placement.workdir,
            *self._env_flags({"HOME": placement.home, **dict(env or {})}),
            self._container,
            *parts,
        ]
        process = subprocess.Popen(  # noqa: S603 — argv built here from the entry registry
            command,
            env=self._cli_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pipe = DockerStdio(process)
        self._attached.append(pipe)
        return pipe

    # --- docker specifics ----------------------------------------------------

    def placement(self) -> Placement:
        """Attach facts. ``target_id`` is the container, opaque above this file."""
        if self._container is None:
            raise EnvironmentFailure("environment_not_started", "docker box is not started")
        return Placement(
            target_id=self._container,
            user=self._user,
            workdir=WORKSPACE_PATH,
            home=HOME_PATH,
        )

    def visible_path(self, box_path: str) -> str:
        """A container really owns ``/attempt``, so the contract path is the path."""
        return box_path

    @property
    def root(self) -> Path:
        return self._root

    def _volume_flags(self) -> list[str]:
        """Bind mounts. Never the docker daemon socket."""
        return ["-v", f"{self._root}:{BOX_ROOT}"]

    def _start_egress_proxy(self) -> list[str]:
        if self._egress != "llm":
            return []
        from ageval.plugins.contrib.docker.egress import AllowlistProxy

        proxy = AllowlistProxy(self._egress_allowlist)
        try:
            proxy.start()
        except RuntimeError as exc:
            raise EnvironmentFailure("environment_options_invalid", str(exc)) from exc
        self._proxy = proxy
        self._proxy_url = f"http://host.docker.internal:{proxy.port}"
        return ["--add-host", "host.docker.internal:host-gateway"]

    def _stop_egress_proxy(self) -> None:
        proxy = self._proxy
        self._proxy = None
        self._proxy_url = None
        stop = getattr(proxy, "stop", None)
        if callable(stop):
            stop()

    def host_path(self, box_path: str) -> Path:
        """Where an in-box path lands on this machine (the bind mount source)."""
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
        return (self._root / rel) if rel else self._root

    def _prepare_work_root(self) -> None:
        """Create the in-box layout, writable by the box's non-root user."""
        self._root.mkdir(parents=True, exist_ok=True)
        _make_box_writable(self._root)
        for path in (WORKSPACE_PATH, HOME_PATH, ARTIFACTS_PATH):
            directory = self.host_path(path)
            directory.mkdir(parents=True, exist_ok=True)
            _make_box_writable(directory)
        # Gold arrives in the evaluate phase; nothing creates it before that.
        assert not self.host_path(EVALUATION_PATH).exists()

    def _env_flags(self, env: Mapping[str, str] | None) -> list[str]:
        """Caller env plus this box's own path publication; never daemon locators."""
        projected = {
            "AGEVAL_WORKSPACE": WORKSPACE_PATH,
            "AGEVAL_ARTIFACTS": ARTIFACTS_PATH,
            "AGEVAL_EVALUATION": EVALUATION_PATH,
            **{k: v for k, v in (env or {}).items() if k not in _DAEMON_ENV_KEYS and v},
        }
        if self._proxy_url:
            projected["HTTP_PROXY"] = self._proxy_url
            projected["HTTPS_PROXY"] = self._proxy_url
            projected["http_proxy"] = self._proxy_url
            projected["https_proxy"] = self._proxy_url
            projected["NO_PROXY"] = ""
            projected["no_proxy"] = ""
        flags: list[str] = []
        for key, value in projected.items():
            flags.extend(["-e", f"{key}={value}"])
        return flags

    def _cli_env(self) -> dict[str, str]:
        """Environment for the docker CLI itself (it must find the daemon)."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        for key in _DAEMON_ENV_KEYS:
            value = os.environ.get(key)
            if value:
                env[key] = value
        return env

    async def _run_docker(
        self,
        args: Sequence[str],
        *,
        timeout_sec: float | None,
    ) -> ExecResult:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            env=self._cli_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            return ExecResult(exit_code=124, stderr="exec timed out")
        return ExecResult(
            exit_code=int(process.returncode or 0),
            stdout=stdout[:_MAX_STREAM_BYTES].decode("utf-8", errors="replace"),
            stderr=stderr[:_MAX_STREAM_BYTES].decode("utf-8", errors="replace"),
            truncated=len(stdout) > _MAX_STREAM_BYTES or len(stderr) > _MAX_STREAM_BYTES,
        )

    # --- compose sidecars ----------------------------------------------------

    def _compose_up(self) -> None:
        project = f"ageval-{uuid.uuid4().hex[:10]}"
        self._compose_project = project
        result = self._compose("up", "-d")
        if result.returncode != 0:
            self._compose_project = None
            raise EnvironmentFailure(
                "environment_compose_failed",
                f"docker compose up failed: {(result.stderr or result.stdout).strip()[-500:]}",
            )

    def _compose(self, *args: str) -> subprocess.CompletedProcess[str]:
        assert self._compose_file is not None
        assert self._compose_project is not None
        return docker(
            "compose",
            "-p",
            self._compose_project,
            "-f",
            str(self._task_root / self._compose_file),
            *args,
        )

    async def _compose_exec(
        self,
        service: str,
        argv: Sequence[str],
        *,
        timeout_sec: float | None,
    ) -> ExecResult:
        if self._compose_project is None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                f"no compose project is up; exec(service={service!r}) is unavailable",
            )
        assert self._compose_file is not None
        return await self._run_docker(
            [
                "compose",
                "-p",
                self._compose_project,
                "-f",
                str(self._task_root / self._compose_file),
                "exec",
                "-T",
                service,
                *argv,
            ],
            timeout_sec=timeout_sec,
        )

    def _assert_started(self) -> None:
        if not self._started:
            raise EnvironmentFailure("environment_not_started", "docker box is not started")
        if self._stopped:
            raise EnvironmentFailure("environment_stopped", "docker box is already stopped")


def _box_python_version(raw: object) -> str | None:
    """Job ``environment_options.python_version``. None = the official 3.12 base."""
    if raw is None:
        return None
    text = _text(raw)
    if text is None or not _PYTHON_VERSION_RE.fullmatch(text):
        raise EnvironmentFailure(
            "environment_options_invalid",
            "docker environment_options.python_version must be a CPython minor "
            f'like "3.13", got {raw!r}',
        )
    return text


def _box_user(raw: object) -> str:
    """Job ``environment_options.user``. Default is the Attempt uid, not root."""
    if raw is None or raw == "":
        return f"{ATTEMPT_UID}:{ATTEMPT_GID}"
    text = _text(raw)
    if text is None:
        raise EnvironmentFailure(
            "environment_options_invalid",
            "docker environment_options.user must be root, a uid, or uid:gid",
        )
    lowered = text.lower()
    if lowered in {"root", "0", "0:0"}:
        return "0:0"
    if ":" in text:
        uid, _, gid = text.partition(":")
        if uid.isdigit() and gid.isdigit():
            return f"{int(uid)}:{int(gid)}"
    elif text.isdigit():
        uid = int(text)
        return f"{uid}:{uid}"
    raise EnvironmentFailure(
        "environment_options_invalid",
        f"docker environment_options.user must be root, a uid, or uid:gid, got {text!r}",
    )


def _make_box_writable(path: Path) -> None:
    """Bind-mounted /attempt is host-owned; chmod so the box uid can write it."""
    with contextlib.suppress(OSError):
        path.chmod(0o777 if path.is_dir() else 0o666)
    if path.is_dir():
        for child in path.rglob("*"):
            with contextlib.suppress(OSError):
                child.chmod(0o777 if child.is_dir() else 0o666)


def _text(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


__all__ = ["BOX_ROOT", "DockerHost", "DockerStdio"]
