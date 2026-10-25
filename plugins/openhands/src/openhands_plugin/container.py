"""In-environment OpenHands executor.

The SDK runs through ``host.exec``. The instruction is a file inside the
environment so a long task prompt is not an argv element. The trajectory is
the worker's JSON file, downloaded afterwards. Stdout is not the transcript.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ageval.environments.protocol import HOME_PATH, WORKSPACE_PATH, EnvironmentFailure, ExecResult
from ageval.evidence.redaction import redact_value
from ageval.model.usage import adopt_usage
from ageval.plugins.agent_result import AgentResult, parse_validated_text_structured
from ageval.plugins.errors import ExtensionMaterializeError
from openhands_plugin import PLUGIN_ID
from openhands_plugin.pin import requirement
from openhands_plugin.trajectory import TRAJECTORY_SCHEMA, to_ageval_trajectory_events

BOX_PLUGIN = f"{HOME_PATH}/_openhands"
BOX_WORKER = f"{BOX_PLUGIN}/ageval_executor_openhands.py"
BOX_INSTRUCTION = f"{BOX_PLUGIN}/instruction.md"
BOX_TRAJECTORY = f"{BOX_PLUGIN}/trajectory.json"
_INSTALL_TIMEOUT_SEC = 600.0
_PROBE = "import openhands.sdk, openhands.tools"


def _run_coro(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class OpenHandsBoxExecutor:
    """Invoke the pinned OpenHands SDK inside the Attempt environment."""

    kind = PLUGIN_ID

    def __init__(
        self,
        *,
        host: Any,
        placement: Any,
        plugin_root: Path,
        version: str,
        max_iterations: int,
        model: str,
        api: str,
        reasoning_effort: str | None,
        timeout: float | None,
        base_url: str | None,
        api_key_env: str | None,
    ) -> None:
        self._host = host
        self._placement = placement
        self._plugin_root = Path(plugin_root)
        self.version = version
        self.max_iterations = max_iterations
        self.model = model
        self.api = api
        self.reasoning_effort = reasoning_effort
        self.model_timeout = timeout
        self.base_url = (base_url or "").strip() or None
        self.api_key_env = (api_key_env or "").strip() or None
        self._prepared = False

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
        try:
            return _run_coro(
                self._ainvoke(
                    prompt,
                    timeout=timeout,
                    collect_dir=collect_dir,
                    redaction_sentinels=redaction_sentinels,
                )
            )
        except ExtensionMaterializeError as exc:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=str(getattr(exc, "message", None) or exc),
                metadata=self._metadata(),
            )

    async def _ainvoke(
        self,
        prompt: str,
        *,
        timeout: float,
        collect_dir: str | os.PathLike[str] | None,
        redaction_sentinels: tuple[str, ...] | list[str] | None,
    ) -> AgentResult:
        from ageval.plugins.step_stream import resume_prefix

        await self._prepare()
        await self._upload_instruction(resume_prefix(getattr(self, "activity", None)) + prompt)
        sentinels = tuple(redaction_sentinels or ())
        key = self._api_key_value()
        if key:
            sentinels = (*sentinels, key)
        from ageval.plugins.step_stream import exec_with_steps

        result = await exec_with_steps(
            self._host,
            self._worker_argv(),
            getattr(self, "activity", None),
            cwd=self._placement.workdir or WORKSPACE_PATH,
            env=self._exec_env(key),
            timeout_sec=timeout,
        )
        document = await self._read_trajectory(sentinels)
        if collect_dir and document is not None:
            root = Path(collect_dir)
            root.mkdir(parents=True, exist_ok=True)
            (root / "openhands_trajectory.json").write_text(
                json.dumps(document, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return self._result_from(result, document, sentinels=sentinels)

    async def _prepare(self) -> None:
        if self._prepared:
            return
        await self._host.upload(
            self._plugin_root / "worker" / "ageval_executor_openhands.py",
            BOX_WORKER,
        )
        await self._ensure_sdk()
        self._prepared = True

    async def _ensure_sdk(self) -> None:
        """Import the pin. If it is missing, install that pin or fail closed."""
        probe = await self._probe()
        if probe.exit_code == 0:
            return
        specs = requirement(self.version)
        install = await self._host.exec(
            [
                *self._python(),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                *specs,
            ],
            cwd=self._placement.workdir or WORKSPACE_PATH,
            timeout_sec=_INSTALL_TIMEOUT_SEC,
        )
        if install.exit_code != 0:
            raise ExtensionMaterializeError(
                "openhands_sdk_install_failed",
                kind="extension_materialize_failed",
            )
        probe = await self._probe()
        if probe.exit_code != 0:
            raise ExtensionMaterializeError(
                "openhands_sdk_missing",
                kind="extension_materialize_failed",
            )

    async def _probe(self) -> ExecResult:
        return await self._host.exec(
            [*self._python(), "-c", _PROBE],
            cwd=self._placement.workdir or WORKSPACE_PATH,
            timeout_sec=60,
        )

    async def _upload_instruction(self, prompt: str) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".md",
            delete=False,
        ) as handle:
            handle.write(prompt)
            path = Path(handle.name)
        try:
            await self._host.upload(path, BOX_INSTRUCTION)
        finally:
            path.unlink(missing_ok=True)

    def _worker_argv(self) -> list[str]:
        visible = self._host.visible_path
        return [
            *self._python(),
            visible(BOX_WORKER),
            "--instruction-file",
            visible(BOX_INSTRUCTION),
            "--trajectory",
            visible(BOX_TRAJECTORY),
            "--workdir",
            visible(self._placement.workdir or WORKSPACE_PATH),
        ]

    def _python(self) -> list[str]:
        return [str(part) for part in self._host.python_command]

    def _api_key_value(self) -> str | None:
        from openhands_plugin.factory import resolve_api_key_value

        return resolve_api_key_value(self.api_key_env)

    def _resolve_base_url(self) -> str | None:
        from openhands_plugin.factory import resolve_base_url

        return resolve_base_url(self.base_url)

    def _exec_env(self, key: str | None) -> dict[str, str]:
        env: dict[str, str] = {
            "OH_MODEL": self.model,
            "OH_API": self.api,
            "OH_MAX_ITERATIONS": str(self.max_iterations),
        }
        if self.reasoning_effort:
            env["OH_REASONING_EFFORT"] = self.reasoning_effort
        if self.model_timeout is not None and self.model_timeout > 0:
            env["OH_TIMEOUT"] = str(int(self.model_timeout))
        if key:
            env["OPENAI_API_KEY"] = key
            env["LLM_API_KEY"] = key
        base = self._resolve_base_url()
        if base:
            env["OPENAI_BASE_URL"] = base
            env["LLM_BASE_URL"] = base
        return env

    async def _read_trajectory(self, sentinels: tuple[str, ...]) -> dict[str, Any] | None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            destination = Path(handle.name)
        try:
            await self._host.download(BOX_TRAJECTORY, destination)
            document = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, EnvironmentFailure, json.JSONDecodeError):
            return None
        finally:
            destination.unlink(missing_ok=True)
        if not isinstance(document, dict):
            return None
        if document.get("schema") != TRAJECTORY_SCHEMA:
            return None
        redacted = redact_value(document, extra_sentinels=sentinels)
        return redacted if isinstance(redacted, dict) else None

    def _result_from(
        self,
        result: Any,
        document: dict[str, Any] | None,
        *,
        sentinels: tuple[str, ...],
    ) -> AgentResult:
        stderr = str(getattr(result, "stderr", "") or "")
        exit_code = int(getattr(result, "exit_code", 1) or 0)
        if sentinels:
            stderr = str(redact_value(stderr, extra_sentinels=sentinels))
        metadata = self._metadata()
        metadata["exit_code"] = exit_code
        if document is None:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="openhands_trajectory_missing",
                stderr=stderr[-2000:],
                repeatable=False,
                metadata=metadata,
            )
        steps = document.get("steps")
        native: tuple[dict[str, Any], ...] = ()
        if isinstance(steps, list):
            native = tuple(step for step in steps if isinstance(step, dict))
        fresh = tuple(to_ageval_trajectory_events(native))
        from ageval.plugins.activity_events import prior_activity_events

        events = tuple(prior_activity_events(getattr(self, "activity", None), fresh))
        text = str(document.get("text") or "")
        error = document.get("error")
        ok = bool(document.get("ok")) and exit_code == 0 and not error
        return AgentResult(
            model=str(document.get("model") or self.model),
            text=text,
            structured=parse_validated_text_structured(text),
            ok=ok,
            error=str(error) if error else None,
            stderr=stderr[-2000:],
            events=events,
            usage=adopt_usage(document.get("usage")),
            repeatable=False,
            metadata=metadata,
        )

    def _metadata(self) -> dict[str, Any]:
        return {
            "plugin": PLUGIN_ID,
            "execution_location": "attempt-container",
            "sdk_version": self.version,
            "max_iterations": self.max_iterations,
        }


__all__ = [
    "BOX_INSTRUCTION",
    "BOX_TRAJECTORY",
    "BOX_WORKER",
    "OpenHandsBoxExecutor",
]
