"""DockerHost — the ``docker`` environment kind.

Everything docker-shaped lives in this file: the container id, the ``docker
exec`` argv, the uid/gid, the compose calls, and the rule that the daemon's own
locator variables must never reach a process inside the box. Above it, the ACP
executor and the Attempt phases see only the environment Protocol.

Files under ``/attempt`` move through the bind mount. Other absolute paths
use ``docker cp``. A compose service uses ``docker compose cp``.
``/attempt/evaluation`` therefore appears exactly when the evaluate phase
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
from pathlib import Path, PurePosixPath

from ageval.environments.box_state import (
    ENV_STATE_DIR,
    INFLIGHT_OUTPUT_NAME,
    ensure_state_dir,
    host_state_dir,
    probe_box,
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
)
from ageval.evidence.redaction import redact_text
from ageval.plugins.base import BaseEnvironment
from ageval.plugins.contrib.docker.compose_parity import (
    AttemptParity,
    compose_declares_services,
    is_runtime_compose,
    prepare_runtime_compose,
    resolve_attempt_parity,
)
from ageval.plugins.contrib.docker.images import (
    daemon_available,
    docker,
    host_platform,
    resolve_image,
)
from ageval.plugins.contrib.docker.resources import (
    DockerRunResources,
    docker_run_resource_args,
    query_gpu_inventory,
    resources_from_options,
    write_sidecar_overlay,
)
from ageval.plugins.decorators import environment_plugin

BOX_ROOT = "/attempt"
ATTEMPT_UID = 10001
ATTEMPT_GID = 10001
# Harbor sidecars dial the agent container by this DNS name. It is registered
# only when the Attempt joins the compose project network.
_COMPOSE_ATTEMPT_ALIAS = "main"
_MAX_STREAM_BYTES = 256 * 1024
_CP_TIMEOUT_SEC = 600.0
_PYTHON_VERSION_RE = re.compile(r"^\d+\.\d+$")
_COMPOSE_SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")

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


@environment_plugin(priority=100, source="first-party")
class DockerHost(BaseEnvironment):
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
        self._build_context = spec.build_context
        self._align_app = bool(opts.get("align_app"))
        self._drop_compose_main = bool(opts.get("drop_compose_main"))
        self._workdir = _text(opts.get("workdir")) or WORKSPACE_PATH
        self._declared_image = _text(opts.get("image") or opts.get("docker_image"))
        self._platform = _text(opts.get("platform")) or host_platform()
        # The Agent runs inside the box and has to reach its provider.
        self._network = _text(opts.get("network")) or "bridge"
        self._user = _box_user(opts.get("user"))
        self._python_version = _box_python_version(opts.get("python_version"))
        self._egress = _text(opts.get("egress"))
        self._network_mode_set = "network_mode" in opts
        self._network_mode = opts.get("network_mode")
        self._cap_add_set = "cap_add" in opts
        self._cap_add = opts.get("cap_add")
        self._main_environment_set = "main_environment" in opts
        self._main_environment = opts.get("main_environment")
        raw_allow = opts.get("egress_allowlist") or ()
        if isinstance(raw_allow, (list, tuple)):
            self._egress_allowlist = tuple(str(item) for item in raw_allow if str(item).strip())
        else:
            self._egress_allowlist = ()
        resources = resources_from_options(opts)
        self._cpus = resources.cpus
        self._memory_mb = resources.memory_mb
        self._gpus = resources.gpus
        self._gpu_types = resources.gpu_types
        self._proxy: object | None = None
        self._proxy_url: str | None = None
        self._container: str | None = None
        self._compose_project: str | None = None
        self._compose_overlay: Path | None = None
        self._compose_runtime: Path | None = None
        self._image: str | None = None
        self._started = False
        self._stopped = False
        self.reattached = False
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
        parity = self._attempt_parity()
        self._reject_service_network(parity)
        self._prepare_work_root()
        tag, _digest = resolve_image(
            task_root=self._task_root or self._repo_root,
            dockerfile_rel=self._dockerfile,
            declared_image=self._declared_image,
            platform=self._platform,
            force_build=force_build,
            plugin_layers=self._plugin_layers,
            python_version=self._python_version,
            context_rel=self._build_context,
        )
        self._image = tag
        # Resolve CPU / memory / GPU before any container exists. A missing GPU
        # fails here, with no compose project and no Attempt container.
        resource_args = self._resource_run_args()
        # Sidecars come up first. The Attempt joins their project network, so a
        # service is reachable by name, and the Attempt is reachable as `main`.
        # service:<name> instead shares that sidecar's network namespace:
        # localhost is the sidecar's localhost, and `main` is not registered.
        network = self._network
        on_compose_network = False
        if self._compose_file is not None and self._compose_up():
            network = f"{self._compose_project}_default"
            on_compose_network = True
        if parity.service is not None:
            network = f"container:{self._sidecar_container_id(parity.service)}"
            on_compose_network = False
        network_flags = ["--network", network]
        if on_compose_network:
            network_flags.extend(["--network-alias", _COMPOSE_ATTEMPT_ALIAS])
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
            *network_flags,
            *resource_args,
            *self._parity_run_flags(parity),
            *extra_run,
            *self._volume_flags(),
            "-w",
            self._workdir,
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
        self.reattached = False
        if self._align_app:
            self._align_workspace_app()

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
        self._discard_compose_runtime()
        self._drop_compose_overlay()
        if self._container is not None:
            docker("rm", "-f", self._container, timeout=120.0)
        if delete and self._root.is_dir():
            shutil.rmtree(self._root, ignore_errors=True)
        if delete and self.state_root.is_dir():
            shutil.rmtree(self.state_root, ignore_errors=True)

    def runtime_handle(self) -> dict[str, object]:
        return {
            "container_id": self._container,
            "compose_project": self._compose_project,
        }

    async def probe(self, handle: Mapping[str, object]) -> ProbeStatus:
        cid = str(handle.get("container_id") or "").strip()
        if not cid or not _container_running(cid):
            return ProbeStatus(status="absent")
        return probe_box(
            self._root,
            pid_alive=lambda pid: _pid_in_container(cid, pid),
            state=self.state_root,
        )

    async def attach(self, handle: Mapping[str, object]) -> None:
        cid = str(handle.get("container_id") or "").strip()
        if not cid or not _container_running(cid):
            msg = "docker container is absent"
            raise EnvironmentFailure("environment_absent", msg)
        self._container = cid
        compose = handle.get("compose_project")
        if isinstance(compose, str) and compose.strip():
            self._compose_project = compose.strip()
        self._root.mkdir(parents=True, exist_ok=True)
        for rel in ("workspace", "home", "artifacts"):
            (self._root / rel).mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._started = True
        self._stopped = False
        self.reattached = True

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
        argv = [str(part) for part in command]
        if not argv:
            raise EnvironmentFailure("environment_exec_invalid", "exec requires a command")
        if service is not None:
            return await self._compose_exec(service, argv, timeout_sec=timeout_sec)
        assert self._container is not None
        child_env = dict(env or {})
        if request_id:
            child_env["AGEVAL_EXEC_REQUEST"] = request_id
            argv = _exec_pid_wrapper(argv)
        prefix = [
            "exec",
            "-u",
            user or self._user,
            "-w",
            cwd or WORKSPACE_PATH,
            *self._env_flags(child_env),
            self._container,
        ]
        result = await self._run_docker(prefix + argv, timeout_sec=timeout_sec)
        if request_id:
            # The wrapper already wrote ``/tmp/.ageval-state``. This overwrite
            # is the same file on the host mount, with the output docker returned.
            folder = ensure_state_dir(self.state_root)
            (folder / INFLIGHT_OUTPUT_NAME).write_text(
                f"{result.stdout}{result.stderr}",
                encoding="utf-8",
            )
            write_last_exit(
                self.state_root,
                {
                    "request_id": request_id,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        return result

    async def upload(self, source: Path, dest: str, *, service: str | None = None) -> None:
        """Copy into the box. ``/attempt`` stays on the bind mount."""
        self._assert_started()
        if service is None and str(dest or "").strip().startswith(BOX_ROOT):
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
                copy_bind_tree(src, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
            _make_box_writable(target)
            return
        await self._cp_into(Path(source), dest, service=service)

    async def download(self, source: str, dest: Path, *, service: str | None = None) -> None:
        self._assert_started()
        if service is None and str(source or "").strip().startswith(BOX_ROOT):
            src = self.host_path(source)
            if not src.exists():
                raise EnvironmentFailure(
                    "environment_download_missing",
                    f"download source does not exist in box: {source}",
                )
            target = Path(dest).expanduser()
            if src.is_dir():
                copy_bind_tree(src, target)
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            return
        await self._cp_out(source, Path(dest), service=service)

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> DockerStdio:
        """Start a foreground process in the container and hand back its pipes."""
        self._assert_started()
        parts = [str(part) for part in argv]
        if not parts:
            raise EnvironmentFailure("environment_attach_invalid", "attach_stdio requires argv")
        assert self._container is not None
        child_env = {"HOME": placement.home, **dict(env or {})}
        if request_id:
            child_env["AGEVAL_EXEC_REQUEST"] = request_id
            child_env["AGEVAL_STATE_DIR"] = ENV_STATE_DIR
            parts = _exec_pid_wrapper(parts)
        command = [
            "docker",
            "exec",
            "-i",
            "-u",
            placement.user or self._user,
            "-w",
            placement.workdir,
            *self._env_flags(child_env),
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

    @property
    def state_root(self) -> Path:
        return host_state_dir(self._root)

    def _volume_flags(self) -> list[str]:
        """Bind mounts. Never the docker daemon socket.

        Recovery files are mounted at ``/tmp/.ageval-state``, outside ``/attempt``.
        """
        self.state_root.mkdir(parents=True, exist_ok=True)
        _make_box_writable(self.state_root)
        return [
            "-v",
            f"{self._root}:{BOX_ROOT}",
            "-v",
            f"{self.state_root}:{ENV_STATE_DIR}",
        ]

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

    def _resource_run_args(self) -> list[str]:
        inventory = query_gpu_inventory() if self._gpus > 0 else ()
        return docker_run_resource_args(
            DockerRunResources(
                cpus=self._cpus,
                memory_mb=self._memory_mb,
                gpus=self._gpus,
                gpu_types=self._gpu_types,
            ),
            inventory,
        )

    def _attempt_parity(self) -> AttemptParity:
        return resolve_attempt_parity(
            task_root=self._task_root,
            compose_file=self._compose_file,
            options=self._parity_options(),
        )

    def _parity_options(self) -> dict[str, object]:
        """Only keys the caller actually set. Omitted keys fall through to the file."""
        options: dict[str, object] = {}
        if self._network_mode_set:
            options["network_mode"] = self._network_mode
        if self._cap_add_set:
            options["cap_add"] = self._cap_add
        if self._main_environment_set:
            options["main_environment"] = self._main_environment
        return options

    def _reject_service_network(self, parity: AttemptParity) -> None:
        if parity.service is None:
            return
        if self._compose_file is None:
            raise EnvironmentFailure(
                "environment_start_failed",
                f"network_mode service:{parity.service} requires environment/compose.yaml",
            )
        if self._egress == "llm":
            raise EnvironmentFailure(
                "environment_options_invalid",
                "network_mode service:* cannot be combined with egress: llm",
            )

    def _parity_run_flags(self, parity: AttemptParity) -> list[str]:
        flags: list[str] = []
        for cap in parity.cap_add:
            flags.extend(["--cap-add", cap])
        for key, value in parity.environment:
            flags.extend(["-e", f"{key}={value}"])
        return flags

    def _sidecar_container_id(self, service: str) -> str:
        result = self._compose("ps", "-q", service)
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if result.returncode != 0 or len(lines) != 1:
            raise EnvironmentFailure(
                "environment_start_failed",
                f"compose service {service!r} did not yield one running container",
            )
        return lines[0]

    def _compose_up(self) -> bool:
        """Start sidecars. False when Harbor removed every service, including main."""
        assert self._compose_file is not None
        overlay = write_sidecar_overlay(self._task_root / self._compose_file)
        if overlay is not None:
            self._compose_overlay = overlay
        project = f"ageval-{uuid.uuid4().hex[:10]}"
        self._compose_project = project
        runtime = prepare_runtime_compose(
            self._task_root / self._compose_file,
            project,
            drop_main=self._drop_compose_main,
        )
        if is_runtime_compose(runtime):
            self._compose_runtime = runtime
        if not compose_declares_services(runtime):
            self._discard_compose_runtime()
            self._compose_project = None
            self._drop_compose_overlay()
            return False
        result = self._compose("up", "-d")
        if result.returncode != 0:
            self._compose("down", "-v")
            self._discard_compose_runtime()
            self._compose_project = None
            self._drop_compose_overlay()
            raise EnvironmentFailure(
                "environment_compose_failed",
                f"docker compose up failed: {(result.stderr or result.stdout).strip()[-500:]}",
            )
        return True

    def _align_workspace_app(self) -> None:
        """Make ``/app`` the same directory as ``/attempt/workspace``.

        Failure removes the container. The Attempt records ``harbor_app_alignment``.
        """
        script = """
set -eu
ws=/attempt/workspace
if [ -d /app ] && [ ! -L /app ]; then
  tar -C /app -cf - . | tar -C "$ws" -xf -
  rm -rf /app
  ln -s "$ws" /app
elif [ ! -e /app ]; then
  ln -s "$ws" /app
elif [ ! -L /app ]; then
  echo "app is not a directory or symlink" >&2
  exit 1
fi
a=$(cd /app && pwd -P)
b=$(cd "$ws" && pwd -P)
[ "$a" = "$b" ]
"""
        assert self._container is not None
        result = docker("exec", "-u", "0", self._container, "sh", "-c", script)
        if result.returncode != 0:
            docker("rm", "-f", self._container, timeout=120.0)
            self._container = None
            self._started = False
            detail = (result.stderr or result.stdout or "").strip()[-300:]
            raise EnvironmentFailure(
                "harbor_app_alignment",
                f"/app is not aligned with /attempt/workspace: {detail}",
            )

    def _drop_compose_overlay(self) -> None:
        path = self._compose_overlay
        self._compose_overlay = None
        if path is not None:
            path.unlink(missing_ok=True)

    def _discard_compose_runtime(self) -> None:
        path = self._compose_runtime
        self._compose_runtime = None
        if path is not None and is_runtime_compose(path):
            path.unlink(missing_ok=True)

    def _compose(self, *args: str) -> subprocess.CompletedProcess[str]:
        assert self._compose_file is not None
        assert self._compose_project is not None
        compose_path = self._compose_runtime or (self._task_root / self._compose_file)
        files = ["-f", str(compose_path)]
        if self._compose_overlay is not None:
            files.extend(["-f", str(self._compose_overlay)])
        return docker(
            "compose",
            "-p",
            self._compose_project,
            *files,
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
        compose_path = self._compose_runtime or (self._task_root / self._compose_file)
        return await self._run_docker(
            [
                "compose",
                "-p",
                self._compose_project,
                "-f",
                str(compose_path),
                "exec",
                "-T",
                service,
                *argv,
            ],
            timeout_sec=timeout_sec,
        )

    async def _cp_out(self, source: str, dest: Path, *, service: str | None) -> None:
        remote = _absolute_container_path(source)
        if service is not None:
            self._check_service(service)
        target = dest.expanduser()
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        result = await self._run_docker(
            self._cp_argv(self._remote_ref(remote, service), str(target), service=service),
            timeout_sec=_CP_TIMEOUT_SEC,
        )
        if result.exit_code != 0 or not target.exists():
            tail = redact_text(result.stderr or "")[-300:]
            raise EnvironmentFailure(
                "environment_collect_missing",
                f"collect copy failed for {remote} exit {result.exit_code}: {tail}",
            )

    async def _cp_into(self, source: Path, dest: str, *, service: str | None) -> None:
        src = source.expanduser()
        if not src.exists():
            raise EnvironmentFailure(
                "environment_upload_missing",
                f"upload source does not exist: {source}",
            )
        remote = _absolute_container_path(dest)
        if service is not None:
            self._check_service(service)
        if src.is_dir():
            removed = await self.exec(["rm", "-rf", remote], timeout_sec=60, service=service)
            if not removed.ok:
                tail = redact_text(removed.stderr or "")[-300:]
                raise EnvironmentFailure(
                    "environment_collect_failed",
                    f"collect copy failed for {remote} exit {removed.exit_code}: {tail}",
                )
        parent = str(PurePosixPath(remote).parent)
        if parent not in {"/", "."}:
            made = await self.exec(["mkdir", "-p", parent], timeout_sec=30, service=service)
            if not made.ok:
                tail = redact_text(made.stderr or "")[-300:]
                raise EnvironmentFailure(
                    "environment_collect_failed",
                    f"collect copy failed for {remote} exit {made.exit_code}: {tail}",
                )
        result = await self._run_docker(
            self._cp_argv(str(src), self._remote_ref(remote, service), service=service),
            timeout_sec=_CP_TIMEOUT_SEC,
        )
        if result.exit_code != 0:
            tail = redact_text(result.stderr or "")[-300:]
            raise EnvironmentFailure(
                "environment_collect_failed",
                f"collect copy failed for {remote} exit {result.exit_code}: {tail}",
            )

    def _check_service(self, service: str) -> str:
        name = service.strip()
        if _COMPOSE_SERVICE_RE.fullmatch(name) is None:
            raise EnvironmentFailure(
                "environment_path_invalid",
                f"compose service name is invalid: {service!r}",
            )
        if self._compose_project is None or self._compose_file is None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                f"no compose project is up; transfer(service={name!r}) is unavailable",
            )
        return name

    def _remote_ref(self, remote: str, service: str | None) -> str:
        if service is None:
            assert self._container is not None
            return f"{self._container}:{remote}"
        return f"{self._check_service(service)}:{remote}"

    def _cp_argv(self, src: str, dst: str, *, service: str | None) -> list[str]:
        if service is None:
            return ["cp", src, dst]
        assert self._compose_project is not None
        assert self._compose_file is not None
        return [
            "compose",
            "-p",
            self._compose_project,
            "-f",
            str(self._task_root / self._compose_file),
            "cp",
            src,
            dst,
        ]

    def _assert_started(self) -> None:
        if not self._started:
            raise EnvironmentFailure("environment_not_started", "docker box is not started")
        if self._stopped:
            raise EnvironmentFailure("environment_stopped", "docker box is already stopped")


def _absolute_container_path(raw: str) -> str:
    text = str(raw or "").strip()
    if not text.startswith("/") or "\\" in text:
        raise EnvironmentFailure(
            "environment_path_invalid",
            f"container path must be absolute: {raw!r}",
        )
    pure = PurePosixPath(text)
    if any(part in {".", ".."} for part in pure.parts):
        raise EnvironmentFailure(
            "environment_path_invalid",
            f"container path escapes its root: {raw!r}",
        )
    normalized = pure.as_posix()
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized


def copy_bind_tree(src: Path, dest: Path) -> None:
    """Copy a docker bind tree onto evidence.

    Workspace venv links point at in-box interpreters. Following them on the
    host raises and aborts harvest (run ERROR). Copy the symlink node.
    """
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True, symlinks=True)


# Shell stays alive until the command exits, so ``inflight.pid`` is this shell.
# Python copies both streams to the state files and to this process's pipes.
# The EXIT trap writes ``last_exit.json`` even when the parent never returns.
_EXEC_WRAPPER = r"""
state=${AGEVAL_STATE_DIR:-/tmp/.ageval-state}
mkdir -p "$state"
umask 000
echo $$ > "$state/inflight.pid"
printf %s "${AGEVAL_EXEC_REQUEST-}" > "$state/inflight.request"
: > "$state/inflight.output"
: > "$state/inflight.stdout"
: > "$state/inflight.stderr"
finish() {
  status="$1"
  trap - EXIT INT TERM
  if [ "${child:-0}" != 0 ]; then
    kill "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
  fi
  AGEVAL_EXEC_CODE="$status" python3 - "$state" <<'PY'
import json, os, sys
from pathlib import Path
state = Path(sys.argv[1])
code = int(os.environ.get("AGEVAL_EXEC_CODE", "1"))

def read(name: str) -> str:
    path = state / name
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")

payload = {
    "request_id": os.environ.get("AGEVAL_EXEC_REQUEST", ""),
    "exit_code": code,
    "stdout": read("inflight.stdout"),
    "stderr": read("inflight.stderr"),
}
tmp = state / f"last_exit.json.tmp.{os.getpid()}"
tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp, state / "last_exit.json")
for name in ("inflight.pid", "inflight.request"):
    try:
        (state / name).unlink()
    except FileNotFoundError:
        pass
PY
  exit "$status"
}
trap 'finish $?' EXIT
trap 'finish 143' TERM
trap 'finish 130' INT
child=0
python3 -u - "$state" "$@" <<'PY' &
import os, signal, subprocess, sys, threading
from pathlib import Path
state = Path(sys.argv[1])
cmd = sys.argv[2:]
if not cmd:
    sys.exit(127)
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    bufsize=0,
    start_new_session=True,
)
out_f = (state / "inflight.stdout").open("ab")
err_f = (state / "inflight.stderr").open("ab")
both = (state / "inflight.output").open("ab")
lock = threading.Lock()

def pump(src, own, shared, mirror) -> None:
    fd = src.fileno()
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                return
            own.write(chunk)
            own.flush()
            mirror.write(chunk)
            mirror.flush()
            with lock:
                shared.write(chunk)
                shared.flush()
    finally:
        src.close()

def _stop(signum, _frame):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)
assert proc.stdout is not None and proc.stderr is not None
threads = (
    threading.Thread(target=pump, args=(proc.stdout, out_f, both, sys.stdout.buffer)),
    threading.Thread(target=pump, args=(proc.stderr, err_f, both, sys.stderr.buffer)),
)
for thread in threads:
    thread.start()
try:
    for thread in threads:
        thread.join()
    code = proc.wait()
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else 1
    raise
finally:
    out_f.close()
    err_f.close()
    both.close()
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait()
sys.exit(code if code >= 0 else 1)
PY
child=$!
wait "$child"
status=$?
finish "$status"
"""


def _exec_pid_wrapper(argv: list[str]) -> list[str]:
    return ["sh", "-c", _EXEC_WRAPPER, "ageval-exec", *argv]


def _container_running(container_id: str) -> bool:
    found = docker("inspect", "-f", "{{.State.Running}}", container_id, timeout=30.0)
    return found.returncode == 0 and (found.stdout or "").strip() == "true"


def _pid_in_container(container_id: str, pid: int) -> bool:
    if pid <= 0:
        return False
    found = docker("exec", container_id, "sh", "-c", f"kill -0 {pid}", timeout=15.0)
    return found.returncode == 0


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
