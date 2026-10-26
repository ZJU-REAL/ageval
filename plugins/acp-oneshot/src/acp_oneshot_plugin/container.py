"""In-box oneshot executor: one ``host.exec`` per invoke."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import gzip
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from acp_oneshot_plugin import PLUGIN_ID
from acp_oneshot_plugin.trajectory import to_ageval_trajectory_events
from ageval.environments.protocol import (
    HOME_PATH,
    WORKSPACE_PATH,
    EnvironmentFailure,
)
from ageval.plugins.agent_result import (
    AgentResult,
    observational_result_health,
    parse_validated_text_structured,
)
from ageval.plugins.contrib.acp.child_env import project_credential_env
from ageval.plugins.contrib.acp.home import home_env
from ageval.plugins.contrib.acp.hooks import (
    resolve_entry_argv0,
    store_entry_argv0,
    stored_entry_argv0,
)

WORKER_ENV = "AGEVAL_ACP_ONESHOT_WORKER"
_BOOTSTRAP = (
    "import base64,gzip,os,sys;"
    "code=gzip.decompress(base64.b64decode(os.environ['AGEVAL_ACP_ONESHOT_WORKER']));"
    "ns={'__name__':'__main__'};"
    "sys.argv[0]='ageval-acp-oneshot';"
    "exec(compile(code,'ageval_acp_oneshot.py','exec'),ns)"
)


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _worker_blob() -> str:
    source = (_plugin_root() / "worker" / "ageval_acp_oneshot.py").read_bytes()
    return base64.b64encode(gzip.compress(source, compresslevel=9)).decode("ascii")


def _run_coro(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class AcpOneshotBoxExecutor:
    """Invoke an in-box ACP pair through ``host.exec``. No live stdio pipe."""

    kind = PLUGIN_ID

    def __init__(
        self,
        *,
        host: Any,
        placement: Any,
        entry_id: str,
        acp_command: list[str],
        model: str,
        reasoning_effort: str | None,
        base_url: str | None,
        api_key_env: str | None,
        profile_id: str | None,
        credential_env_names: tuple[str, ...] | list[str],
        fixed_env: dict[str, str],
        descriptor: Any,
    ) -> None:
        self._host = host
        self._placement = placement
        self.entry_id = entry_id
        self.acp_command = [str(part) for part in acp_command]
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.base_url = (base_url or "").strip() or None
        self.api_key_env = (api_key_env or "").strip() or None
        self.profile_id = profile_id
        self.credential_env_names = tuple(credential_env_names)
        self.fixed_env = dict(fixed_env)
        self._descriptor = descriptor
        self._worker_b64 = _worker_blob()

    @staticmethod
    def describe() -> dict[str, Any]:
        from acp_oneshot_plugin.factory import describe_acp_oneshot

        return describe_acp_oneshot()

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
        if os.environ.get("AGEVAL_OFFLINE_AGENT") == "1":
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="offline_forced",
                events=(
                    {
                        "type": "lifecycle",
                        "phase": "skipped",
                        "reason": "offline_forced",
                        "source": PLUGIN_ID,
                    },
                ),
                metadata={"plugin": PLUGIN_ID, "executor_kind": PLUGIN_ID},
            )
        return _run_coro(self._ainvoke(prompt, timeout=timeout, collect_dir=collect_dir))

    async def _ainvoke(
        self,
        prompt: str,
        *,
        timeout: float,
        collect_dir: str | os.PathLike[str] | None,
    ) -> AgentResult:
        workdir = self._placement.workdir or WORKSPACE_PATH
        cwd = self._host.visible_path(workdir)
        box_result = f"{HOME_PATH}/.acp-oneshot-result.json"
        argv = list(self.acp_command)
        argv0 = stored_entry_argv0(self._host, self.entry_id)
        already_absolute = bool(argv) and str(argv[0]).startswith("/")
        if argv0 is None and not already_absolute:
            argv0 = await resolve_entry_argv0(self._host, self._descriptor)
            if argv0:
                store_entry_argv0(self._host, self.entry_id, argv0)
        if argv0:
            argv[0] = argv0
        elif not already_absolute:
            raise EnvironmentFailure(
                "acp_runtime_missing",
                f"acp entry {self.entry_id!r} has no pinned binary",
            )
        from ageval.plugins.contrib.acp.activity_stream import (
            native_session_id,
            prompt_for_resume,
        )

        scope = getattr(self, "activity", None)
        native = native_session_id(scope)
        request = {
            "prompt": prompt_for_resume(scope, prompt, resumed_native=bool(native)),
            "cwd": cwd,
            "acp_command": argv,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "entry_id": self.entry_id,
            "timeout_sec": float(timeout),
            "protocol_version": 1,
            "result_path": self._host.visible_path(box_result),
        }
        from ageval.plugins.step_stream import exec_with_steps

        env = self._exec_env()
        if native:
            env["AGEVAL_NATIVE_SESSION"] = native
        result = await exec_with_steps(
            self._host,
            [*self._host.python_command, "-c", _BOOTSTRAP, json.dumps(request, sort_keys=True)],
            scope,
            cwd=workdir,
            env=env,
            timeout_sec=timeout,
        )
        payload = _payload_from_stdout(str(getattr(result, "stdout", "") or ""))
        if payload is None:
            payload = await self._payload_from_file(box_result)
        return self._result_from(result, collect_dir=collect_dir, payload=payload)

    def _exec_env(self) -> dict[str, str]:
        home = self._host.visible_path(self._placement.home or HOME_PATH)
        env = home_env(self._descriptor, home)
        env.update(
            project_credential_env(
                self.entry_id,
                credential_env_names=self.credential_env_names,
                api_key_env=self.api_key_env,
                base_url=self.base_url,
            )
        )
        for key, value in self.fixed_env.items():
            if value:
                env[str(key)] = str(value)
        env[WORKER_ENV] = self._worker_b64
        env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
        env.setdefault("LANG", "C.UTF-8")
        return env

    async def _payload_from_file(self, box_path: str) -> dict[str, Any] | None:
        download = getattr(self._host, "download", None)
        if not callable(download):
            return None
        dest = Path(tempfile.mkdtemp(prefix="acp-oneshot-")) / "result.json"
        try:
            await download(box_path, dest)
            data = json.loads(dest.read_text(encoding="utf-8"))
        except (EnvironmentFailure, OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _result_from(
        self,
        result: Any,
        *,
        collect_dir: str | os.PathLike[str] | None,
        payload: dict[str, Any] | None = None,
    ) -> AgentResult:
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        exit_code = int(getattr(result, "exit_code", 1) or 0)
        if payload is None:
            payload = _payload_from_stdout(stdout)
        if collect_dir and payload is not None:
            root = Path(collect_dir)
            root.mkdir(parents=True, exist_ok=True)
            (root / "acp_oneshot.json").write_text(
                json.dumps(payload, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )
        if payload is None:
            return AgentResult(
                model=self.model,
                text=stdout[-2000:],
                structured=None,
                ok=False,
                error="acp_oneshot_unreadable" if exit_code == 0 else "acp_oneshot_failed",
                stderr=stderr[-2000:],
                metadata={
                    "plugin": PLUGIN_ID,
                    "executor_kind": PLUGIN_ID,
                    "acp_entry_id": self.entry_id,
                    "execution_location": "attempt-container",
                    "exit_code": exit_code,
                },
            )
        events_raw = payload.get("events") or ()
        fresh = tuple(
            to_ageval_trajectory_events(
                tuple(e for e in events_raw if isinstance(e, dict)),
                session_id=str(payload.get("session_id") or "acp-oneshot"),
            )
        )
        from ageval.plugins.activity_events import prior_activity_events

        events = tuple(prior_activity_events(getattr(self, "activity", None), fresh))
        ok = bool(payload.get("ok", False))
        text = str(payload.get("text") or "")
        error = str(payload["error"]) if payload.get("error") else None
        from ageval.model.usage import adopt_usage

        raw_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        usage = adopt_usage(
            raw_usage,
            timeout=error in {"acp_timeout", "acp_idle_timeout"},
        )
        actual_model = payload.get("actual_model") or self.model
        health = observational_result_health(
            ok=ok,
            usage=usage,
            actual_model=actual_model,
            events=events,
        )
        metadata = {
            "plugin": PLUGIN_ID,
            "executor_kind": PLUGIN_ID,
            "acp_entry_id": self.entry_id,
            "execution_location": "attempt-container",
            "exit_code": exit_code,
            "stop_reason": payload.get("stop_reason"),
            "protocol_version": payload.get("protocol_version"),
            "agent_info": payload.get("agent_info"),
            "locked_model": self.model,
            "actual_model": actual_model,
            "locked_reasoning_effort": self.reasoning_effort,
        }
        if health:
            metadata["result_health"] = health
        return AgentResult(
            model=str(actual_model),
            text=text,
            structured=parse_validated_text_structured(text) if ok else None,
            ok=ok,
            error=error,
            stderr=stderr[-2000:],
            events=events,
            usage=usage,
            metadata=metadata,
        )


def _payload_from_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["AcpOneshotBoxExecutor"]
