"""In-box nooa executor: run the worker through the environment Protocol."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from pathlib import Path
from typing import Any

from ageval.environments.protocol import HOME_PATH, WORKSPACE_PATH
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.errors import ExtensionMaterializeError
from nooa_plugin import PLUGIN_ID

BOX_PLUGIN = f"{HOME_PATH}/_nooa"
BOX_WORKER = f"{BOX_PLUGIN}/ageval_executor_nooa.py"
BOX_SRC = f"{BOX_PLUGIN}/src"
BOX_PACKAGE = "/attempt/package"


def _run_coro(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class NooaBoxExecutor:
    """Invoke a task-local nooa agent inside the Attempt box via ``host.exec``."""

    kind = PLUGIN_ID

    def __init__(
        self,
        *,
        host: Any,
        placement: Any,
        plugin_root: Path,
        package_root: str | None,
        agent_ref: str,
        method: str,
        model: str,
        base_url: str | None,
        api_key_env: str | None,
    ) -> None:
        self._host = host
        self._placement = placement
        self._plugin_root = Path(plugin_root)
        self._package_root = Path(package_root) if package_root else None
        self.agent_ref = agent_ref
        self.method = method or "run"
        self.model = model
        self.base_url = (base_url or "").strip() or None
        self.api_key_env = (api_key_env or "").strip() or None
        self._prepared = False

    @staticmethod
    def describe() -> dict[str, Any]:
        from nooa_plugin.factory import describe_nooa

        return describe_nooa()

    def open(self, **kwargs: Any) -> None:
        del kwargs

    def close(self) -> None:
        return None

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        collect_dir: str | os.PathLike[str] | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
    ) -> AgentResult:
        del redaction_sentinels
        try:
            return _run_coro(self._ainvoke(prompt, timeout=timeout, collect_dir=collect_dir))
        except ExtensionMaterializeError as exc:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=str(getattr(exc, "message", None) or exc),
                metadata={
                    "plugin": PLUGIN_ID,
                    "agent": self.agent_ref,
                    "execution_location": "attempt-container",
                },
            )

    async def _ainvoke(
        self,
        prompt: str,
        *,
        timeout: float,
        collect_dir: str | os.PathLike[str] | None,
    ) -> AgentResult:
        from ageval.plugins.step_stream import resume_prefix

        await self._prepare()
        request = {
            "prompt": resume_prefix(getattr(self, "activity", None)) + prompt,
            "agent": self.agent_ref,
            "method": self.method,
            "model": self.model,
            "package_root": self._host.visible_path(BOX_PACKAGE),
            "workdir": self._host.visible_path(self._placement.workdir or WORKSPACE_PATH),
        }
        base = self._resolve_base_url()
        if base:
            request["api_base"] = base
        from ageval.plugins.step_stream import exec_with_steps

        result = await exec_with_steps(
            self._host,
            [
                *self._host.python_command,
                self._host.visible_path(BOX_WORKER),
                json.dumps(request, sort_keys=True),
            ],
            getattr(self, "activity", None),
            cwd=self._placement.workdir or WORKSPACE_PATH,
            env=self._exec_env(),
            timeout_sec=timeout,
        )
        return self._result_from(result, collect_dir=collect_dir)

    async def _prepare(self) -> None:
        if self._prepared:
            return
        await self._host.upload(
            self._plugin_root / "worker" / "ageval_executor_nooa.py", BOX_WORKER
        )
        await self._host.upload(self._plugin_root / "src" / "nooa_plugin", f"{BOX_SRC}/nooa_plugin")
        await self._upload_agent_module()
        await _ensure_import(
            self._host,
            self._placement,
            module="nooa",
            spec="nooa>=0.0.7",
        )
        self._prepared = True

    async def _upload_agent_module(self) -> None:
        if self._package_root is None or not self._package_root.is_dir():
            raise ExtensionMaterializeError(
                "nooa_package_root_missing",
                kind="extension_materialize_failed",
            )
        top = self.agent_ref.split(":", 1)[0].split(".", 1)[0]
        src = self._package_root / top
        file_src = self._package_root / f"{top}.py"
        if src.is_dir():
            await self._host.upload(src, f"{BOX_PACKAGE}/{top}")
            return
        if file_src.is_file():
            await self._host.upload(file_src, f"{BOX_PACKAGE}/{top}.py")
            return
        raise ExtensionMaterializeError(
            f"nooa_agent_source_missing:{top}",
            kind="extension_materialize_failed",
        )

    def _resolve_base_url(self) -> str | None:
        from nooa_plugin.factory import resolve_base_url

        return resolve_base_url(self.base_url)

    def _exec_env(self) -> dict[str, str]:
        from nooa_plugin.factory import resolve_api_key_value

        env: dict[str, str] = {
            "NOOA_MODEL": self.model,
            "PYTHONPATH": self._host.visible_path(BOX_SRC),
        }
        key = resolve_api_key_value(self.api_key_env)
        if key:
            env["OPENAI_API_KEY"] = key
        base = self._resolve_base_url()
        if base:
            env["OPENAI_BASE_URL"] = base
        if os.environ.get("AGEVAL_OFFLINE_AGENT") == "1":
            env["AGEVAL_OFFLINE_AGENT"] = "1"
        return env

    def _result_from(
        self, result: Any, *, collect_dir: str | os.PathLike[str] | None
    ) -> AgentResult:
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        exit_code = int(getattr(result, "exit_code", 1) or 0)
        payload = _payload_from_stdout(stdout)
        if collect_dir and payload is not None:
            root = Path(collect_dir)
            root.mkdir(parents=True, exist_ok=True)
            (root / "nooa_worker.json").write_text(
                json.dumps(payload, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )
        if payload is None:
            return AgentResult(
                model=self.model,
                text=stdout[-2000:],
                structured=None,
                ok=False,
                error="nooa_worker_unreadable" if exit_code == 0 else "nooa_worker_failed",
                stderr=stderr[-2000:],
                metadata={
                    "plugin": PLUGIN_ID,
                    "agent": self.agent_ref,
                    "execution_location": "attempt-container",
                    "exit_code": exit_code,
                },
            )
        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault("plugin", PLUGIN_ID)
        metadata.setdefault("agent", self.agent_ref)
        metadata.setdefault("execution_location", "attempt-container")
        structured = payload.get("structured")
        events = payload.get("events") or ()
        usage = payload.get("usage")
        return AgentResult(
            model=str(payload.get("model") or self.model),
            text=str(payload.get("text") or ""),
            structured=structured if isinstance(structured, dict) else None,
            ok=bool(payload.get("ok", True)),
            error=str(payload["error"]) if payload.get("error") else None,
            stderr=stderr[-2000:],
            events=tuple(events) if isinstance(events, list) else (),
            usage=usage if isinstance(usage, dict) else None,
            metadata=metadata,
        )


async def _ensure_import(host: Any, placement: Any, *, module: str, spec: str) -> None:
    """Import ``module`` in the box; bootstrap pip / CPython when the image has none.

    Debian-style templates often ship ``python3`` without ``pip`` or
    ``ensurepip``, and PEP 668 then needs ``--break-system-packages``. Some
    wheels (nooa) require 3.12+ while the box still has 3.11.
    """
    cwd = placement.workdir or WORKSPACE_PATH
    notes: list[str] = []

    async def _run(argv: list[str], *, timeout_sec: float) -> Any:
        return await host.exec(argv, cwd=cwd, timeout_sec=timeout_sec)

    def _py() -> list[str]:
        return [str(part) for part in host.python_command]

    def _tail(result: Any) -> str:
        return str(getattr(result, "stderr", None) or getattr(result, "stdout", "") or "")[-300:]

    probe = await _run([*_py(), "-c", f"import {module}"], timeout_sec=30)
    if probe.exit_code == 0:
        return

    async def _install() -> bool:
        for extra in ([], ["--break-system-packages"], ["--user", "--break-system-packages"]):
            last = await _run(
                [
                    *_py(),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--disable-pip-version-check",
                    *extra,
                    spec,
                ],
                timeout_sec=300,
            )
            notes.append(_tail(last))
            if last.exit_code != 0:
                continue
            check = await _run([*_py(), "-c", f"import {module}"], timeout_sec=30)
            if check.exit_code == 0:
                return True
            notes.append(_tail(check))
        return False

    async def _ensure_pip() -> bool:
        pip_probe = await _run([*_py(), "-m", "pip", "--version"], timeout_sec=30)
        if pip_probe.exit_code == 0:
            return True
        boot = await _run([*_py(), "-m", "ensurepip", "--default-pip"], timeout_sec=120)
        notes.append(f"ensurepip:{_tail(boot)}")
        if boot.exit_code == 0:
            return True
        fetched = await _run([*_py(), "-c", _GET_PIP], timeout_sec=60)
        notes.append(f"get-pip-fetch:{_tail(fetched)}")
        if fetched.exit_code != 0:
            return False
        for extra in (["--break-system-packages"], ["--user", "--break-system-packages"]):
            inst = await _run([*_py(), "/tmp/get-pip.py", *extra], timeout_sec=180)
            notes.append(f"get-pip:{_tail(inst)}")
            if inst.exit_code == 0:
                return True
        return False

    if await _ensure_pip() and await _install():
        return
    if (
        _needs_newer_python(notes)
        and await _bootstrap_cpython(host, notes, run=_run)
        and await _ensure_pip()
        and await _install()
    ):
        return

    raise RuntimeError(
        f"box missing {module}; pip install {spec} failed: "
        + " | ".join(n for n in notes if n)[-800:]
    )


_GET_PIP = (
    "import urllib.request; "
    "urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')"
)

_BOOTSTRAP_CPYTHON = """
set -e
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12
for cand in /attempt/home/_ageval-py /tmp/ageval-py; do
  if uv venv "$cand" --python 3.12; then
    echo "AGEVAL_VENV=$cand"
    exit 0
  fi
done
echo "AGEVAL_VENV="
exit 1
"""


def _needs_newer_python(notes: list[str]) -> bool:
    blob = "\n".join(notes).lower()
    return any(
        needle in blob
        for needle in (
            "requires-python",
            "does not match your python",
            "could not find a version that satisfies",
        )
    )


async def _bootstrap_cpython(host: Any, notes: list[str], *, run: Any) -> bool:
    """Install CPython 3.12 in the box and point ``host.python_command`` at it."""
    result = await run(["sh", "-c", _BOOTSTRAP_CPYTHON], timeout_sec=180)
    notes.append(
        f"cpython:{(getattr(result, 'stderr', '') or getattr(result, 'stdout', '') or '')[-300:]}"
    )
    if int(getattr(result, "exit_code", 1)) != 0:
        return False
    venv = ""
    for line in str(getattr(result, "stdout", "") or "").splitlines():
        if line.startswith("AGEVAL_VENV="):
            venv = line.split("=", 1)[1].strip()
    if not venv:
        return False
    host.python_command = (f"{venv}/bin/python",)
    return True


def _payload_from_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["BOX_WORKER", "NooaBoxExecutor"]
