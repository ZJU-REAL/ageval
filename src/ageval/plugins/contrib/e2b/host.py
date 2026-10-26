"""E2BHost — the ``e2b`` environment kind.

The same ``environment/Dockerfile`` a docker box builds becomes an e2b template
here, keyed by the recipe's own digest so a rebuilt recipe gets a new template
and an unchanged one is reused. Every mention of the vendor SDK, the template
alias and the sandbox id lives in this package.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from ageval.environments.protocol import (
    ARTIFACTS_PATH,
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
    parse_state_document,
    push_restored_tree,
    state_command,
    wrapper_line,
)
from ageval.plugins.base import BaseEnvironment
from ageval.plugins.decorators import environment_plugin

API_KEY_ENV = "E2B_API_KEY"
_API_KEY_ALIASES = (API_KEY_ENV, "e2b_api_key")
BOX_ROOT = "/attempt"
_MAX_STREAM_BYTES = 256 * 1024


class E2BStdio:
    """ACP needs real fds. Pump the sandbox command onto OS pipes."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle
        self.stderr = None
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self.stdin: IO[bytes] = os.fdopen(in_w, "wb", buffering=0)
        self.stdout: IO[bytes] = os.fdopen(out_r, "rb", buffering=0)
        self._in_r: IO[bytes] = os.fdopen(in_r, "rb", buffering=0)
        self._out_w: IO[bytes] = os.fdopen(out_w, "wb", buffering=0)
        threading.Thread(target=self._pump_in, name="e2b-stdin", daemon=True).start()
        threading.Thread(target=self._pump_out, name="e2b-stdout", daemon=True).start()

    def _pump_in(self) -> None:
        send = getattr(self._handle, "send_stdin", None)
        try:
            while True:
                chunk = self._in_r.read(4096)
                if not chunk:
                    break
                if callable(send):
                    send(chunk.decode("utf-8", errors="replace"))
        finally:
            with contextlib.suppress(OSError):
                self._in_r.close()

    def _pump_out(self) -> None:
        try:
            for event in self._handle:
                text = _stdout_from_event(event)
                if not text:
                    continue
                payload = text.encode("utf-8") if isinstance(text, str) else bytes(text)
                self._out_w.write(payload)
                self._out_w.flush()
        finally:
            with contextlib.suppress(OSError):
                self._out_w.close()

    def terminate(self) -> None:
        kill = getattr(self._handle, "kill", None)
        if callable(kill):
            kill()
        for stream in (self.stdin, self.stdout, self._in_r, self._out_w):
            with contextlib.suppress(OSError):
                stream.close()

    def wait(self, timeout: float | None = None) -> int | None:
        del timeout
        wait = getattr(self._handle, "wait", None)
        if not callable(wait):
            return None
        result = wait()
        return int(getattr(result, "exit_code", 0) or 0)


@environment_plugin(priority=100, source="first-party")
class E2BHost(BaseEnvironment):
    """An ephemeral cloud sandbox per Attempt.

    No shared filesystem with this machine, so files really move: upload writes
    bytes into the sandbox and download reads them back.
    """

    kind = "e2b"
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
        self._task_root = spec.task_root
        self._dockerfile = spec.dockerfile
        self._declared_image = _text(opts.get("image") or opts.get("docker_image"))
        # Exact dashboard alias: skip Dockerfile build. Distinct from the
        # default prefix used when we hash a recipe into ``name__digest``.
        self._ready_template = _text(opts.get("template_id"))
        self._template_name = _text(opts.get("template")) or "ageval-attempt"
        self._timeout_seconds = _seconds(opts.get("timeout_seconds"), default=900)
        self._sandbox: Any = None
        self._script_ready = False
        self._started = False
        self._stopped = False

    # --- lifecycle -----------------------------------------------------------

    async def preflight(self) -> None:
        """No key, no sandbox — and no attempt to create one."""
        if not _api_key():
            raise EnvironmentFailure(
                "environment_preflight_failed",
                f"{API_KEY_ENV} is not set; the e2b kind cannot open a sandbox",
            )
        _import_sdk()

    async def start(self, *, force_build: bool = False) -> None:
        if self._started:
            raise EnvironmentFailure("environment_already_started", "e2b sandbox already started")
        sdk = _import_sdk()
        template = await self._ensure_template(sdk, force_build=force_build)
        self._sandbox = await asyncio.to_thread(
            sdk.Sandbox.create,
            template=template,
            timeout=self._timeout_seconds,
        )
        self._started = True
        try:
            await asyncio.to_thread(self._open_attempt_tree)
        except EnvironmentFailure:
            await self.stop(delete=True)
            raise
        except Exception as exc:  # noqa: BLE001 — vendor errors become a start failure
            await self.stop(delete=True)
            raise EnvironmentFailure(
                "environment_start_failed",
                f"could not prepare {BOX_ROOT}: {exc}"[:300],
            ) from exc

    async def stop(self, *, delete: bool) -> None:
        # Ephemeral by nature: keeping it alive is not on offer, and evidence
        # records that plainly rather than pretending --keep-workspace worked.
        del delete
        if self._stopped or self._sandbox is None:
            return
        self._stopped = True
        await asyncio.to_thread(self._sandbox.kill)

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
                "e2b does not provide uid_gid; exec(user=…) is unavailable",
            )
        if service is not None:
            raise EnvironmentFailure(
                "environment_capability_missing",
                "e2b does not provide compose; exec(service=…) is unavailable",
            )
        argv = [str(part) for part in command]
        if not argv:
            raise EnvironmentFailure("environment_exec_invalid", "exec requires a command")
        if request_id:
            await self._ensure_sync_script()
            argv = ["sh", "-c", wrapper_line(request_id, _shell_line(argv))]
        try:
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                _shell_line(argv),
                cwd=cwd or WORKSPACE_PATH,
                envs=self._child_env(env),
                timeout=int(timeout_sec) if timeout_sec else 0,
            )
        except Exception as exc:  # noqa: BLE001 — vendor raises on nonzero
            code = getattr(exc, "exit_code", None)
            if code is None:
                raise
            return ExecResult(
                exit_code=int(code or 1),
                stdout=str(getattr(exc, "stdout", "") or "")[:_MAX_STREAM_BYTES],
                stderr=str(getattr(exc, "stderr", "") or str(exc))[:_MAX_STREAM_BYTES],
            )
        return ExecResult(
            exit_code=int(getattr(result, "exit_code", 0) or 0),
            stdout=str(getattr(result, "stdout", "") or "")[:_MAX_STREAM_BYTES],
            stderr=str(getattr(result, "stderr", "") or "")[:_MAX_STREAM_BYTES],
        )

    async def upload(self, source: Path, dest: str, *, service: str | None = None) -> None:
        self._assert_started()
        reject_foreign_service(service, kind="e2b", verb="upload")
        src = Path(source).expanduser()
        if not src.exists():
            raise EnvironmentFailure(
                "environment_upload_missing",
                f"upload source does not exist: {source}",
            )
        for path, target in _walk_for_upload(src, dest):
            payload = path.read_bytes()
            await asyncio.to_thread(self._sandbox.files.write, target, payload)

    async def download(self, source: str, dest: Path, *, service: str | None = None) -> None:
        """Copy a file or a directory's contents. ``files.read`` is files only."""
        self._assert_started()
        reject_foreign_service(service, kind="e2b", verb="download")
        target = Path(dest).expanduser()
        try:
            info = await asyncio.to_thread(self._sandbox.files.get_info, source)
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
        if _entry_kind(info) == "file":
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
            payload = await asyncio.to_thread(self._sandbox.files.read, path, "bytes")
        except Exception as exc:  # noqa: BLE001 — vendor read
            raise EnvironmentFailure(
                "environment_download_failed",
                f"read {path} failed: {exc}",
            ) from exc
        return bytes(payload)

    async def _walk_files(self, root: str) -> list[str]:
        """Immediate children, then recurse. Depth-1 list is the portable API."""
        try:
            entries = await asyncio.to_thread(self._sandbox.files.list, root, 1)
        except Exception as exc:  # noqa: BLE001 — vendor list
            raise EnvironmentFailure(
                "environment_download_failed",
                f"list {root} failed: {exc}",
            ) from exc
        found: list[str] = []
        for entry in entries or ():
            path = _remote_path(root, entry)
            kind = _entry_kind(entry)
            if kind == "file":
                found.append(path)
            elif kind == "dir" and path.rstrip("/") != root.rstrip("/"):
                found.extend(await self._walk_files(path))
        return found

    async def attach_stdio(
        self,
        argv: Sequence[str],
        *,
        placement: Placement,
        env: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> E2BStdio:
        """Start a foreground command in the sandbox and hand back its streams."""
        self._assert_started()
        parts = [str(part) for part in argv]
        if not parts:
            raise EnvironmentFailure("environment_attach_invalid", "attach_stdio requires argv")
        from ageval.environments.remote_state import stdio_inflight_argv

        child_env = {"HOME": placement.home, **self._child_env(env)}
        if request_id:
            child_env["AGEVAL_EXEC_REQUEST"] = request_id
            parts = stdio_inflight_argv(parts)
        handle = await asyncio.to_thread(
            self._sandbox.commands.run,
            _shell_line(parts),
            background=True,
            cwd=placement.workdir,
            envs=child_env,
            stdin=True,
            timeout=0,
        )
        return E2BStdio(handle)

    # --- e2b specifics -------------------------------------------------------

    def runtime_handle(self) -> dict[str, object]:
        sid = getattr(self._sandbox, "sandbox_id", None)
        return {"sandbox_id": str(sid)} if sid else {}

    async def probe(self, handle: Mapping[str, object]) -> ProbeStatus:
        sid = str(handle.get("sandbox_id") or "").strip()
        if not sid:
            return ProbeStatus(status="absent")
        try:
            sdk = _import_sdk()
            sandbox = await asyncio.to_thread(sdk.Sandbox.connect, sid)
        except Exception:  # noqa: BLE001 — a dead or unknown sandbox is absent
            return ProbeStatus(status="absent")
        self._sandbox = sandbox
        try:
            await self._ensure_sync_script()
            result = await self._run_line(_shell_line(state_command("dump")))
        except Exception:  # noqa: BLE001 — unreadable state is absent
            return ProbeStatus(status="absent")
        return parse_state_document(result.stdout)

    async def attach(self, handle: Mapping[str, object]) -> None:
        status = await self.probe(handle)
        if status.status == "absent" or self._sandbox is None:
            raise EnvironmentFailure(
                "environment_attach_invalid",
                "e2b sandbox is not available to attach",
            )
        self._started = True
        self._stopped = False

    async def push_restored_box(self, box: Path) -> None:
        await push_restored_tree(self, box)

    def mirror_checkpoint(self, dest: Path) -> None:
        if self._sandbox is None:
            return
        self._write_script_sync()
        out = "/tmp/ageval-checkpoint.tar"
        self._sandbox.commands.run(
            _shell_line(state_command("pack", out)),
            cwd="/",
            timeout=120,
        )
        blob = self._sandbox.files.read(out, "bytes")
        from ageval.environments.remote_state import apply_checkpoint_tar

        raw = blob if isinstance(blob, bytes) else bytes(blob)
        apply_checkpoint_tar(dest, raw)

    async def _ensure_sync_script(self) -> None:
        if self._script_ready or self._sandbox is None:
            return
        await asyncio.to_thread(self._write_script_sync)
        self._script_ready = True

    def _open_attempt_tree(self) -> None:
        """``/attempt`` is owned by the image user. The sandbox user must be able to write it."""
        self._sandbox.commands.run(attempt_tree_command(), cwd="/", timeout=60)

    def sync_box_state(self, box: Path) -> None:
        if self._sandbox is None:
            return
        from ageval.environments.remote_state import local_state_files

        self._write_script_sync()
        for path, remote in local_state_files(box):
            self._sandbox.files.write(remote, path.read_bytes())

    def _write_script_sync(self) -> None:
        self._sandbox.files.make_dir("/tmp/.ageval-state")
        self._sandbox.files.write(
            f"/tmp/.ageval-state/{CHECKPOINT_SYNC_NAME}",
            CHECKPOINT_SYNC_SCRIPT,
        )

    async def _run_line(self, line: str) -> ExecResult:
        try:
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                line,
                cwd="/",
                timeout=60,
            )
        except Exception as exc:  # noqa: BLE001 — vendor raises on nonzero
            code = getattr(exc, "exit_code", None)
            if code is None:
                raise
            return ExecResult(exit_code=int(code or 1), stdout="", stderr=str(exc)[:400])
        return ExecResult(
            exit_code=int(getattr(result, "exit_code", 0) or 0),
            stdout=str(getattr(result, "stdout", "") or ""),
            stderr=str(getattr(result, "stderr", "") or ""),
        )

    def placement(self) -> Placement:
        if self._sandbox is None:
            raise EnvironmentFailure("environment_not_started", "e2b sandbox is not started")
        return Placement(
            target_id=str(getattr(self._sandbox, "sandbox_id", "e2b")),
            user=None,
            workdir=WORKSPACE_PATH,
            home=HOME_PATH,
        )

    def visible_path(self, box_path: str) -> str:
        """The sandbox really owns ``/attempt``."""
        return box_path

    async def _ensure_template(self, sdk: Any, *, force_build: bool) -> str:
        """Reuse a template keyed by the recipe; build it only when new."""
        if self._ready_template:
            return self._ready_template
        if self._declared_image is not None and self._dockerfile is None:
            return await self._build_template(
                sdk, from_image=self._declared_image, force=force_build
            )
        if self._dockerfile is None:
            raise EnvironmentFailure(
                "environment_image_unresolved",
                "the e2b kind needs environment/Dockerfile or an image option",
            )
        return await self._build_template(sdk, from_image=None, force=force_build)

    async def _build_template(self, sdk: Any, *, from_image: str | None, force: bool) -> str:
        alias = self._alias(from_image)
        if not force and await sdk.AsyncTemplate.alias_exists(alias):
            return alias
        context = str(self._task_root)
        builder = sdk.Template(file_context_path=context)
        template = (
            builder.from_image(from_image)
            if from_image is not None
            else builder.from_dockerfile(str(self._task_root / str(self._dockerfile)))
        )
        await sdk.AsyncTemplate.build(template, alias=alias)
        return alias

    def _alias(self, from_image: str | None) -> str:
        """``<name>__<recipe digest>``: a new recipe is a new template."""
        material = (
            from_image.encode("utf-8")
            if from_image is not None
            else (self._task_root / str(self._dockerfile)).read_bytes()
        )
        return f"{self._template_name}__{hashlib.sha256(material).hexdigest()[:12]}"

    def _child_env(self, env: Mapping[str, str] | None) -> dict[str, str]:
        """Only what the caller declared, plus this box's path publication."""
        out = {str(k): str(v) for k, v in (env or {}).items() if v}
        out.setdefault("AGEVAL_WORKSPACE", WORKSPACE_PATH)
        out.setdefault("AGEVAL_ARTIFACTS", ARTIFACTS_PATH)
        out.setdefault("AGEVAL_EVALUATION", f"{BOX_ROOT}/evaluation")
        return out

    def _assert_started(self) -> None:
        if not self._started or self._sandbox is None:
            raise EnvironmentFailure("environment_not_started", "e2b sandbox is not started")
        if self._stopped:
            raise EnvironmentFailure("environment_stopped", "e2b sandbox is already killed")


def _stdout_from_event(event: Any) -> str | bytes | None:
    """Background ``commands.run`` yields ``(stdout, stderr, _)`` tuples."""
    if isinstance(event, tuple):
        return event[0] if event else None
    text = getattr(event, "stdout", None)
    return text if text else None


def attempt_tree_command() -> str:
    """Make the agent directories writable. Recovery state stays under ``/tmp``."""
    paths = f"{WORKSPACE_PATH} {HOME_PATH} {ARTIFACTS_PATH}"
    state = "/tmp/.ageval-state"
    return (
        f"(mkdir -p {paths} {state} && chmod -R a+rwx {paths} {state}) "
        f"|| (sudo mkdir -p {paths} {state} && sudo chmod -R a+rwx {paths} {state})"
    )


def _api_key() -> str:
    """SDK reads ``E2B_API_KEY``; accept the lowercase locator too."""
    for name in _API_KEY_ALIASES:
        val = os.environ.get(name, "").strip()
        if val:
            if name != API_KEY_ENV:
                os.environ[API_KEY_ENV] = val
            return val
    return ""


def _import_sdk() -> Any:
    try:
        import e2b  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — depends on the install extra
        raise EnvironmentFailure(
            "environment_preflight_failed",
            "the e2b kind needs the e2b extra: "
            "uv tool install 'ageval-cli[e2b]' (repo checkout: uv sync --extra e2b)",
        ) from exc
    return e2b


def _walk_for_upload(source: Path, dest: str) -> list[tuple[Path, str]]:
    """File-by-file plan; a sandbox has no shared filesystem to copy into."""
    if source.is_file():
        return [(source, dest)]
    plan: list[tuple[Path, str]] = []
    for path in sorted(source.rglob("*")):
        if path.is_file():
            plan.append((path, f"{dest}/{path.relative_to(source).as_posix()}"))
    return plan


def _shell_line(argv: Sequence[str]) -> str:
    import shlex

    return " ".join(shlex.quote(str(part)) for part in argv)


def _seconds(raw: object, *, default: int) -> int:
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _text(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _entry_kind(entry: Any) -> str:
    kind = getattr(entry, "type", None)
    value = getattr(kind, "value", kind)
    text = str(value or "").strip().lower()
    if text in {"file", "filetype.file"}:
        return "file"
    if text in {"dir", "directory", "filetype.dir"}:
        return "dir"
    return text


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
    if name in {"FileNotFoundException", "NotFoundException", "FileNotFoundError"}:
        return True
    return "not found" in str(exc).lower()


__all__ = ["API_KEY_ENV", "E2BHost", "E2BStdio"]
