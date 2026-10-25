"""DaytonaHost — the ``daytona`` environment kind.

Vendor SDK, snapshot names and sandbox ids live only in this package.
``BoxCapabilities.attach_stdio`` is a kind constant, frozen after an
implementation-time ACP handshake (not probed on every start).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shlex
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

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
    state_command,
    wrapper_line,
)
from ageval.plugins.base import BaseEnvironment
from ageval.plugins.decorators import environment_plugin

API_KEY_ENV = "DAYTONA_API_KEY"
_API_KEY_ALIASES = (API_KEY_ENV, "daytona_api_key")
BOX_ROOT = "/attempt"
_MAX_STREAM_BYTES = 256 * 1024
_FORBIDDEN_TAGS = frozenset({"latest", "lts", "stable"})

# Frozen after the implementation-time handshake in this issue.
# Session stdin (`send_session_command_input`) is the preferred pump;
# PTY is not the default (TTY echo / CRLF).
ATTACH_STDIO = True


class DaytonaStdio:
    """ACP needs real fds. Pump a Daytona session command onto OS pipes."""

    def __init__(self, sandbox: Any, session_id: str, cmd_id: str) -> None:
        self._sandbox = sandbox
        self._session_id = session_id
        self._cmd_id = cmd_id
        self.stderr = None
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self.stdin: IO[bytes] = os.fdopen(in_w, "wb", buffering=0)
        self.stdout: IO[bytes] = os.fdopen(out_r, "rb", buffering=0)
        self._in_r: IO[bytes] = os.fdopen(in_r, "rb", buffering=0)
        self._out_w: IO[bytes] = os.fdopen(out_w, "wb", buffering=0)
        threading.Thread(target=self._pump_in, name="daytona-stdin", daemon=True).start()
        threading.Thread(target=self._pump_out, name="daytona-stdout", daemon=True).start()

    def _pump_in(self) -> None:
        send = self._sandbox.process.send_session_command_input
        try:
            while True:
                chunk = self._in_r.read(4096)
                if not chunk:
                    break
                try:
                    send(
                        self._session_id,
                        self._cmd_id,
                        chunk.decode("utf-8", errors="replace"),
                    )
                except Exception as exc:  # noqa: BLE001 — command already gone
                    if "already completed" in str(exc).lower() or "not found" in str(exc).lower():
                        break
                    raise
        finally:
            with contextlib.suppress(OSError):
                self._in_r.close()

    def _pump_out(self) -> None:
        seen = 0
        getter = self._sandbox.process.get_session_command_logs
        status = self._sandbox.process.get_session_command
        try:
            while True:
                try:
                    logs = getter(self._session_id, self._cmd_id)
                except Exception as exc:  # noqa: BLE001 — session gone after terminate
                    if "not found" in str(exc).lower():
                        break
                    raise
                text = str(getattr(logs, "stdout", None) or getattr(logs, "output", None) or "")
                if len(text) > seen:
                    self._out_w.write(text[seen:].encode("utf-8"))
                    self._out_w.flush()
                    seen = len(text)
                cmd = status(self._session_id, self._cmd_id)
                if getattr(cmd, "exit_code", None) is not None:
                    break
                time.sleep(0.05)
        finally:
            with contextlib.suppress(OSError):
                self._out_w.close()

    def terminate(self) -> None:
        with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
            self._sandbox.process.delete_session(self._session_id)
        for stream in (self.stdin, self.stdout, self._in_r, self._out_w):
            with contextlib.suppress(OSError):
                stream.close()

    def wait(self, timeout: float | None = None) -> int | None:
        del timeout
        cmd = self._sandbox.process.get_session_command(self._session_id, self._cmd_id)
        code = getattr(cmd, "exit_code", None)
        return int(code) if code is not None else None


@environment_plugin(priority=100, source="first-party")
class DaytonaHost(BaseEnvironment):
    """An ephemeral Daytona sandbox per Attempt."""

    kind = "daytona"
    python_command = ("python3",)
    capabilities = EnvironmentCapabilities(
        exec=True,
        upload=True,
        download=True,
        attach_stdio=ATTACH_STDIO,
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
        self._task_root = spec.task_root
        self._dockerfile = spec.dockerfile
        self._declared_image = _text(opts.get("image") or opts.get("docker_image"))
        self._ready_snapshot = _text(opts.get("snapshot") or opts.get("snapshot_id"))
        self._snapshot_name = _text(opts.get("snapshot_name")) or "ageval-attempt"
        self._timeout_seconds = _seconds(opts.get("timeout_seconds"), default=900)
        self._client: Any = None
        self._sandbox: Any = None
        self._started = False
        self._stopped = False

    async def preflight(self) -> None:
        if not _api_key():
            raise EnvironmentFailure(
                "environment_preflight_failed",
                f"{API_KEY_ENV} is not set; the daytona kind cannot open a sandbox",
            )
        _import_sdk()

    async def start(self, *, force_build: bool = False) -> None:
        if self._started:
            raise EnvironmentFailure(
                "environment_already_started",
                "daytona sandbox already started",
            )
        sdk = _import_sdk()
        self._client = sdk.Daytona()
        snapshot = await self._ensure_snapshot(sdk, force_build=force_build)
        create_params = sdk.CreateSandboxFromSnapshotParams(
            snapshot=snapshot,
            auto_stop_interval=_auto_stop_minutes(self._timeout_seconds),
            ephemeral=True,
        )
        self._sandbox = await asyncio.to_thread(self._client.create, create_params)
        self._started = True
        paths = f"{WORKSPACE_PATH} {HOME_PATH} {ARTIFACTS_PATH} {EVALUATION_PATH}"
        state = "/tmp/.ageval-state"
        mkdir = (
            f"(mkdir -p {paths} {state} && chmod -R a+rwx {paths} {state}) "
            f"|| (sudo mkdir -p {paths} {state} && sudo chmod -R a+rwx {paths} {state})"
        )
        try:
            result = await asyncio.to_thread(self._sandbox.process.exec, mkdir)
            code = getattr(result, "exit_code", None)
            if code is None or int(code) != 0:
                raise EnvironmentFailure(
                    "environment_start_failed",
                    f"could not create {BOX_ROOT}: {getattr(result, 'result', '')!s}"[:300],
                )
        except Exception:
            await self.stop(delete=True)
            raise

    async def stop(self, *, delete: bool) -> None:
        del delete
        if self._stopped or self._sandbox is None:
            return
        self._stopped = True
        sandbox = self._sandbox
        client = self._client
        self._sandbox = None
        if client is not None:
            await asyncio.to_thread(client.delete, sandbox)

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
                "daytona does not provide uid_gid; exec(user=…) is unavailable",
            )
        if service is not None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                "daytona does not provide compose; exec(service=…) is unavailable",
            )
        argv = [str(part) for part in command]
        if not argv:
            raise EnvironmentFailure("environment_exec_invalid", "exec requires a command")
        if request_id:
            self._write_sync_script()
            argv = ["sh", "-c", wrapper_line(request_id, _shell_line(argv))]
        kwargs: dict[str, Any] = {
            "cwd": cwd or WORKSPACE_PATH,
            "env": self._child_env(env),
        }
        if timeout_sec:
            kwargs["timeout"] = int(timeout_sec)
        try:
            result = await asyncio.to_thread(
                self._sandbox.process.exec,
                _shell_line(argv),
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — vendor raises on nonzero
            code = getattr(exc, "exit_code", None)
            if code is None:
                raise
            return ExecResult(
                exit_code=int(code or 1),
                stdout=str(getattr(exc, "stdout", "") or getattr(exc, "result", "") or "")[
                    :_MAX_STREAM_BYTES
                ],
                stderr=str(getattr(exc, "stderr", "") or str(exc))[:_MAX_STREAM_BYTES],
            )
        stdout = str(
            getattr(result, "result", None)
            or getattr(getattr(result, "artifacts", None), "stdout", None)
            or getattr(result, "stdout", "")
            or ""
        )
        return ExecResult(
            exit_code=int(getattr(result, "exit_code", 0) or 0),
            stdout=stdout[:_MAX_STREAM_BYTES],
            stderr=str(getattr(result, "stderr", "") or "")[:_MAX_STREAM_BYTES],
        )

    async def upload(self, source: Path, dest: str, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="daytona", verb="upload")
        src = Path(source).expanduser()
        if not src.exists():
            raise EnvironmentFailure(
                "environment_upload_missing",
                f"upload source does not exist: {source}",
            )
        for path, target in _walk_for_upload(src, dest):
            parent = str(Path(target).parent)
            if parent not in {"/", ""}:
                quoted = shlex.quote(parent)
                await asyncio.to_thread(
                    self._sandbox.process.exec,
                    f"mkdir -p {quoted} && chmod -R a+rwx {quoted}",
                )
            payload = path.read_bytes()
            await asyncio.to_thread(self._sandbox.fs.upload_file, payload, target)

    async def download(self, source: str, dest: Path, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="daytona", verb="download")
        target = Path(dest).expanduser()
        try:
            info = await asyncio.to_thread(self._sandbox.fs.get_file_info, source)
        except Exception as exc:  # noqa: BLE001 — vendor stat
            if _is_missing(exc):
                raise EnvironmentFailure(
                    "environment_download_missing",
                    f"download source does not exist in box: {source}",
                ) from exc
            raise EnvironmentFailure(
                "environment_download_failed",
                f"stat {source} failed: {exc}",
            ) from exc
        if not bool(getattr(info, "is_dir", False)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(await self._read_bytes(source))
            return
        target.mkdir(parents=True, exist_ok=True)
        for remote in await self._walk_files(source):
            rel = _rel_to(remote, source)
            if rel is None:
                continue
            local = target / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(await self._read_bytes(remote))

    async def _read_bytes(self, path: str) -> bytes:
        try:
            payload = await asyncio.to_thread(self._sandbox.fs.download_file, path)
        except Exception as exc:  # noqa: BLE001 — vendor read
            raise EnvironmentFailure(
                "environment_download_failed",
                f"read {path} failed: {exc}",
            ) from exc
        return bytes(payload)

    async def _walk_files(self, root: str) -> list[str]:
        try:
            entries = await asyncio.to_thread(self._sandbox.fs.list_files, root, 1)
        except Exception as exc:  # noqa: BLE001 — vendor list
            raise EnvironmentFailure(
                "environment_download_failed",
                f"list {root} failed: {exc}",
            ) from exc
        found: list[str] = []
        for entry in entries or ():
            path = _remote_path(root, entry)
            if bool(getattr(entry, "is_dir", False)) and path.rstrip("/") != root.rstrip("/"):
                found.extend(await self._walk_files(path))
            elif not bool(getattr(entry, "is_dir", False)):
                found.append(path)
        return found

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
    ) -> DaytonaStdio:
        """Start a foreground command and hand back fileno() pipes."""
        self._assert_started()
        parts = [str(part) for part in argv]
        if not parts:
            raise EnvironmentFailure("environment_attach_invalid", "attach_stdio requires argv")
        session_id = f"ageval-stdio-{uuid.uuid4().hex[:12]}"
        await asyncio.to_thread(self._sandbox.process.create_session, session_id)
        sdk = _import_sdk()
        command = _login_command(parts, cwd=placement.workdir, env=self._child_env(env))
        request = sdk.SessionExecuteRequest(
            command=command,
            run_async=True,
            suppress_input_echo=True,
        )
        result = await asyncio.to_thread(
            self._sandbox.process.execute_session_command,
            session_id,
            request,
        )
        cmd_id = str(getattr(result, "cmd_id", "") or "")
        if not cmd_id:
            raise EnvironmentFailure(
                "environment_attach_invalid",
                "daytona session command did not return cmd_id",
            )
        return DaytonaStdio(self._sandbox, session_id, cmd_id)

    def runtime_handle(self) -> dict[str, object]:
        sid = getattr(self._sandbox, "id", None) or getattr(self._sandbox, "sandbox_id", None)
        return {"sandbox_id": str(sid)} if sid else {}

    async def probe(self, handle: Mapping[str, object]) -> ProbeStatus:
        sid = str(handle.get("sandbox_id") or "").strip()
        if not sid:
            return ProbeStatus(status="absent")
        try:
            client = self._client or self._connect_client()
            sandbox = await asyncio.to_thread(client.get, sid)
        except Exception:  # noqa: BLE001 — a dead sandbox is absent
            return ProbeStatus(status="absent")
        self._sandbox = sandbox
        try:
            self._write_sync_script()
            result = await asyncio.to_thread(
                self._sandbox.process.exec,
                " ".join(state_command("dump")),
                cwd="/",
                timeout=60,
            )
        except Exception:  # noqa: BLE001 — unreadable state is absent
            return ProbeStatus(status="absent")
        return parse_state_document(str(getattr(result, "result", "") or ""))

    async def attach(self, handle: Mapping[str, object]) -> None:
        status = await self.probe(handle)
        if status.status == "absent" or self._sandbox is None:
            raise EnvironmentFailure(
                "environment_attach_invalid",
                "daytona sandbox is not available to attach",
            )
        self._started = True
        self._stopped = False

    async def push_restored_box(self, box: Path) -> None:
        await push_restored_tree(self, box)

    def mirror_checkpoint(self, dest: Path) -> None:
        if self._sandbox is None:
            return
        self._write_sync_script()
        out = "/tmp/ageval-checkpoint.tar"
        self._sandbox.process.exec(" ".join(state_command("pack", out)), cwd="/", timeout=120)
        blob = self._sandbox.fs.download_file(out)
        raw = blob if isinstance(blob, bytes) else bytes(blob)
        apply_checkpoint_tar(dest, raw)

    def sync_box_state(self, box: Path) -> None:
        if self._sandbox is None:
            return
        from ageval.environments.remote_state import local_state_files

        self._write_sync_script()
        for path, remote in local_state_files(box):
            self._sandbox.fs.upload_file(path.read_bytes(), remote)

    def _write_sync_script(self) -> None:
        self._sandbox.fs.upload_file(
            CHECKPOINT_SYNC_SCRIPT.encode(),
            f"/tmp/.ageval-state/{CHECKPOINT_SYNC_NAME}",
        )

    def _connect_client(self) -> Any:
        from daytona import Daytona

        self._client = Daytona()
        return self._client

    def placement(self) -> Placement:
        if self._sandbox is None:
            raise EnvironmentFailure("environment_not_started", "daytona sandbox is not started")
        target = (
            getattr(self._sandbox, "id", None)
            or getattr(self._sandbox, "sandbox_id", None)
            or "daytona"
        )
        return Placement(
            target_id=str(target),
            user=None,
            workdir=WORKSPACE_PATH,
            home=HOME_PATH,
        )

    def visible_path(self, box_path: str) -> str:
        return box_path

    async def _ensure_snapshot(self, sdk: Any, *, force_build: bool) -> str:
        if self._ready_snapshot:
            return self._ready_snapshot
        if self._declared_image is not None:
            _assert_image_tag(self._declared_image)
            return await self._create_snapshot(sdk, image=self._declared_image, force=force_build)
        if self._dockerfile is None:
            raise EnvironmentFailure(
                "environment_image_unresolved",
                "the daytona kind needs environment/Dockerfile, an image option, or a snapshot",
            )
        return await self._create_snapshot(sdk, image=None, force=force_build)

    async def _create_snapshot(self, sdk: Any, *, image: str | None, force: bool) -> str:
        name = self._alias(image)
        if not force:
            existing = await self._existing_snapshot(name)
            if existing:
                return name
        if image is not None:
            params = sdk.CreateSnapshotParams(name=name, image=image)
        else:
            dockerfile = self._task_root / str(self._dockerfile)
            image_obj = sdk.Image.from_dockerfile(str(dockerfile))
            params = sdk.CreateSnapshotParams(name=name, image=image_obj)
        await asyncio.to_thread(self._client.snapshot.create, params)
        return name

    async def _existing_snapshot(self, name: str) -> bool:
        try:
            snap = await asyncio.to_thread(self._client.snapshot.get, name)
        except Exception as exc:  # noqa: BLE001 — vendor missing-snapshot
            msg = str(exc).lower()
            if "not found" in msg or "does not exist" in msg:
                return False
            raise
        state = str(getattr(snap, "state", "") or "").lower()
        if "active" not in state:
            await asyncio.to_thread(self._client.snapshot.activate, name)
        return True

    def _alias(self, from_image: str | None) -> str:
        if from_image is not None:
            material = from_image.encode("utf-8")
        else:
            material = (self._task_root / str(self._dockerfile)).read_bytes()
        digest = hashlib.sha256(material).hexdigest()[:12]
        return f"{self._snapshot_name}-{digest}"

    def _child_env(self, env: Mapping[str, str] | None) -> dict[str, str]:
        out = {str(k): str(v) for k, v in (env or {}).items() if v}
        # Snapshot PATH includes nvm globals. A host Darwin PATH must not leak
        # in; a short Unix allowlist must not hide those globals either.
        # attach_stdio already leaves PATH unset so the session keeps this PATH.
        incoming = out.get("PATH", "")
        if incoming and ("/Users/" in incoming or "/Library/" in incoming):
            out.pop("PATH", None)
        out.setdefault("HOME", HOME_PATH)
        out.setdefault("AGEVAL_WORKSPACE", WORKSPACE_PATH)
        out.setdefault("AGEVAL_ARTIFACTS", ARTIFACTS_PATH)
        out.setdefault("AGEVAL_EVALUATION", EVALUATION_PATH)
        return out

    def _assert_started(self) -> None:
        if not self._started or self._sandbox is None:
            raise EnvironmentFailure("environment_not_started", "daytona sandbox is not started")
        if self._stopped:
            raise EnvironmentFailure("environment_stopped", "daytona sandbox is already stopped")


def _login_command(argv: Sequence[str], *, cwd: str, env: Mapping[str, str]) -> str:
    """Foreground argv in cwd. Not a login shell; ACP needs the process stdin."""
    # Leave PATH to the sandbox so npm-global entries stay visible.
    skip = {"PATH"}
    assignments = " ".join(
        f"{shlex.quote(k)}={shlex.quote(v)}" for k, v in env.items() if k not in skip and v
    )
    body = _shell_line(argv)
    prefix = f"cd {shlex.quote(cwd)} && "
    if assignments:
        return f"{prefix}env {assignments} {body}"
    return prefix + body


def _api_key() -> str:
    for name in _API_KEY_ALIASES:
        val = os.environ.get(name, "").strip()
        if val:
            if name != API_KEY_ENV:
                os.environ[API_KEY_ENV] = val
            return val
    return ""


def _import_sdk() -> Any:
    try:
        import daytona  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — depends on the install extra
        raise EnvironmentFailure(
            "environment_preflight_failed",
            "the daytona kind needs the daytona extra: "
            "uv tool install 'ageval-cli[daytona]' (repo checkout: uv sync --extra daytona)",
        ) from exc
    return daytona


def _assert_image_tag(image: str) -> None:
    last = image.split("/")[-1]
    if "@" in last:
        return
    if ":" not in last:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"daytona snapshot image {image!r} must include a tag or digest "
            "(latest/lts/stable are rejected)",
        )
    tag = last.rsplit(":", 1)[-1].lower()
    if tag in _FORBIDDEN_TAGS:
        raise EnvironmentFailure(
            "environment_image_unresolved",
            f"daytona snapshot image tag {tag!r} is not allowed",
        )


def _walk_for_upload(source: Path, dest: str) -> list[tuple[Path, str]]:
    if source.is_file():
        return [(source, dest)]
    plan: list[tuple[Path, str]] = []
    for path in sorted(source.rglob("*")):
        if path.is_file():
            plan.append((path, f"{dest}/{path.relative_to(source).as_posix()}"))
    return plan


def _shell_line(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def _seconds(raw: object, *, default: int) -> int:
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _auto_stop_minutes(seconds: int) -> int:
    """Daytona ``auto_stop_interval`` is minutes. 0 means never auto-stop."""
    return max(1, (int(seconds) + 59) // 60)


def _text(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _remote_path(root: str, entry: Any) -> str:
    path = str(getattr(entry, "path", "") or "").strip()
    if path.startswith("/"):
        return path
    name = str(getattr(entry, "name", "") or path).strip()
    if not name:
        return root
    return f"{root.rstrip('/')}/{name.lstrip('/')}"


def _rel_to(path: str, root: str) -> str | None:
    root_n = root.rstrip("/")
    path_n = path.rstrip("/")
    if path_n == root_n:
        return None
    prefix = f"{root_n}/"
    if not path_n.startswith(prefix):
        return None
    rel = path_n[len(prefix) :]
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return None
    return rel


def _is_missing(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in {"FileNotFoundException", "NotFoundException", "FileNotFoundError", "DaytonaError"}:
        return "not found" in str(exc).lower() or name != "DaytonaError"
    return "not found" in str(exc).lower()


__all__ = ["API_KEY_ENV", "ATTACH_STDIO", "DaytonaHost", "DaytonaStdio"]
