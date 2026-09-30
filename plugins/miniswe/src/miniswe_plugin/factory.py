"""miniswe ExecutorSPI — host mini-swe-agent loop, bash via environment.exec."""

from __future__ import annotations

import concurrent.futures
import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

from ageval.plugins.agent_result import AgentResult, parse_validated_text_structured
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.http_loopback import is_http_loopback
from ageval.runtime.upstream_stall import current_stall
from miniswe_plugin import PLUGIN_ID
from miniswe_plugin.env import ProtocolEnv
from miniswe_plugin.stall import (
    StallExhausted,
    install_single_package_attempt,
    wait_excluding_stall,
    wrap_model_query,
)
from miniswe_plugin.trajectory import to_ageval_trajectory_events
from miniswe_plugin.usage import usage_from_messages

_CREDENTIAL_ENV_NAMES = ("OPENAI_API_KEY", "litellm_api_key", "LITELLM_API_KEY")
_BASE_URL_ENV_FALLBACKS = ("OPENAI_BASE_URL", "litellm_base_url", "LITELLM_BASE_URL")
_EXTRA_BODY_RESERVED = frozenset({"model", "api_key", "api_base", "drop_params"})


def describe_miniswe() -> dict[str, Any]:
    return {
        "execution_mode": "host-loop",
        "tools": "bash",
        "structured_output": "validated-text",
        "session": "one-shot",
        "stream": "none",
        "credential_env_names": _CREDENTIAL_ENV_NAMES,
        "binary": "",
    }


def _offline() -> bool:
    return os.environ.get("AGEVAL_OFFLINE_AGENT") == "1"


def _as_positive_int(raw: Any, *, name: str, default: int) -> int:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ExtensionMaterializeError(
            f"miniswe_{name}_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ExtensionMaterializeError(
            f"miniswe_{name}_invalid:{raw!r}",
            kind="extension_materialize_failed",
        ) from exc
    if value < 0:
        raise ExtensionMaterializeError(
            f"miniswe_{name}_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    return value


def _as_nonneg_float(raw: Any, *, name: str, default: float) -> float:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ExtensionMaterializeError(
            f"miniswe_{name}_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ExtensionMaterializeError(
            f"miniswe_{name}_invalid:{raw!r}",
            kind="extension_materialize_failed",
        ) from exc
    if value < 0:
        raise ExtensionMaterializeError(
            f"miniswe_{name}_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    return value


def _as_optional_effort(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ExtensionMaterializeError(
            f"miniswe_reasoning_effort_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    return raw.strip()


def _as_extra_body(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, dict):
        raise ExtensionMaterializeError(
            f"miniswe_extra_body_invalid:{raw!r}",
            kind="extension_materialize_failed",
        )
    out: dict[str, Any] = {}
    reserved: list[str] = []
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ExtensionMaterializeError(
                f"miniswe_extra_body_invalid:{raw!r}",
                kind="extension_materialize_failed",
            )
        name = key.strip()
        if name in _EXTRA_BODY_RESERVED:
            reserved.append(name)
            continue
        out[name] = copy.deepcopy(value)
    if reserved:
        raise ExtensionMaterializeError(
            "miniswe_extra_body_reserved:" + ",".join(sorted(reserved)),
            kind="extension_materialize_failed",
        )
    return out


def resolve_api_key_value(locator: str | None) -> str | None:
    names: list[str] = []
    if locator and str(locator).strip():
        names.append(str(locator).strip())
    for name in _CREDENTIAL_ENV_NAMES:
        if name not in names:
            names.append(name)
    for name in names:
        val = os.environ.get(name)
        if val and str(val).strip():
            return str(val).strip()
    return None


def resolve_base_url(explicit: str | None) -> str | None:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for key in _BASE_URL_ENV_FALLBACKS:
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()
    return None


def _config_search_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import minisweagent

        roots.append(Path(minisweagent.package_dir) / "config")
        roots.append(Path(minisweagent.__file__).resolve().parent / "config")
    except Exception:
        pass
    try:
        from importlib.resources import files

        roots.append(Path(str(files("minisweagent").joinpath("config"))))
    except Exception:
        pass
    # Last resort: official mini.yaml copied into the plugin (not a ageval-authored prompt).
    roots.append(Path(__file__).resolve().parents[2] / "vendor")
    return roots


def _load_official_mini_config() -> dict[str, Any]:
    """Read official mini-swe-agent templates (installed package, then plugin vendor)."""
    try:
        import yaml
    except ImportError as exc:
        raise ExtensionMaterializeError(
            "miniswe_config_missing: PyYAML required to read official mini.yaml",
            kind="extension_materialize_failed",
        ) from exc
    names = ("mini.yaml", "default.yaml", "mini_textbased.yaml")
    tried: list[str] = []
    for root in _config_search_roots():
        for name in names:
            path = root / name
            tried.append(str(path))
            if path.is_file():
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("agent"):
                    return data
    raise ExtensionMaterializeError(
        "miniswe_config_missing: no official mini.yaml; tried " + " | ".join(tried),
        kind="extension_materialize_failed",
    )


def _write_backend_raw(collect_dir: str | None, payload: dict[str, Any]) -> None:
    if not collect_dir:
        return
    root = Path(collect_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "miniswe.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2) + "\n",
        encoding="utf-8",
    )


class MinisweExecutorSPI:
    """Executor SPI. The box runs the shell; the LLM client stays on this side."""

    kind = PLUGIN_ID

    def __init__(
        self,
        *,
        host: Any,
        placement: Any,
        options: dict[str, Any] | None = None,
        profile_id: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        plugin_id: str | None = None,
        **_kwargs: Any,
    ) -> None:
        del plugin_id
        opts = dict(options or {})
        self.host = host
        self.placement = placement
        self.options = opts
        self.profile_id = profile_id
        self.model = (model or "").strip() or "openai/gpt-4o-mini"
        self.base_url = base_url if isinstance(base_url, str) else None
        self.api_key_env = api_key if isinstance(api_key, str) else None
        self.step_limit = _as_positive_int(opts.get("step_limit"), name="step_limit", default=30)
        self.cost_limit = _as_nonneg_float(opts.get("cost_limit"), name="cost_limit", default=0.0)
        self.cmd_timeout = _as_positive_int(opts.get("cmd_timeout"), name="cmd_timeout", default=30)
        self.reasoning_effort = _as_optional_effort(opts.get("reasoning_effort"))
        self.extra_body = _as_extra_body(opts.get("extra_body"))
        self.session_id = f"ageval-{self.profile_id or 'solver'}-{uuid.uuid4().hex[:12]}"
        self.execution_location = getattr(host, "kind", None) or "box"
        self._ready = False

    @staticmethod
    def describe() -> dict[str, Any]:
        return describe_miniswe()

    def open(self, **kwargs: Any) -> None:
        del kwargs
        if _offline():
            raise ExtensionMaterializeError(
                "offline_forced",
                kind="extension_materialize_failed",
            )
        self._ready = True

    def close(self) -> None:
        self._ready = False

    def invoke(
        self,
        prompt: str,
        *,
        timeout: float = 60.0,
        workdir: str | None = None,
        collect_dir: str | None = None,
        redaction_sentinels: tuple[str, ...] | list[str] | None = None,
    ) -> AgentResult:
        del redaction_sentinels, workdir
        if _offline():
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="offline_forced",
                metadata={"plugin": PLUGIN_ID},
            )
        try:
            extra = self._run_agent(prompt, timeout=timeout)
        except StallExhausted as exc:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="stall_exhausted",
                metadata={
                    "plugin": PLUGIN_ID,
                    "session_id": self.session_id,
                    "stall_exhausted": True,
                    "reason": str(exc),
                },
            )
        except ExtensionMaterializeError as exc:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=str(getattr(exc, "message", None) or exc),
                metadata={"plugin": PLUGIN_ID},
            )
        except TimeoutError:
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error="miniswe_timeout",
                metadata={"plugin": PLUGIN_ID, "session_id": self.session_id},
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(
                model=self.model,
                text="",
                structured=None,
                ok=False,
                error=f"{type(exc).__name__}:{exc}",
                metadata={"plugin": PLUGIN_ID, "session_id": self.session_id},
            )
        messages = extra.get("messages") if isinstance(extra.get("messages"), list) else []
        _write_backend_raw(collect_dir, extra)
        mapped = tuple(to_ageval_trajectory_events(messages, session_id=self.session_id))
        submission = str(extra.get("submission") or extra.get("exit_content") or "")
        status = str(extra.get("exit_status") or "")
        ok = status == "Submitted"
        location = self.execution_location
        usage = usage_from_messages(messages)
        reported_cost = usage.get("cost_usd") if isinstance(usage, dict) else None
        metadata: dict[str, Any] = {
            "plugin": PLUGIN_ID,
            "session_id": self.session_id,
            "exit_status": status,
            "execution_location": location,
            "n_calls": extra.get("n_calls"),
            "locked_reasoning_effort": self.reasoning_effort,
            "actual_reasoning_effort": self.reasoning_effort,
        }
        if reported_cost is not None:
            metadata["cost"] = reported_cost
        return AgentResult(
            model=self.model,
            text=submission,
            structured=parse_validated_text_structured(submission),
            ok=ok,
            error=None if ok else (status or "miniswe_error"),
            events=mapped,
            usage=usage,
            metadata=metadata,
        )

    def _make_env(self) -> ProtocolEnv:
        return ProtocolEnv(host=self.host, placement=self.placement, timeout=self.cmd_timeout)

    def _litellm_model_kwargs(self, *, key: str | None, base: str | None) -> dict[str, Any]:
        model_kwargs: dict[str, Any] = {"drop_params": True}
        if key:
            model_kwargs["api_key"] = key
        if base:
            model_kwargs["api_base"] = base
        if self.reasoning_effort:
            model_kwargs["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            model_kwargs.update(copy.deepcopy(self.extra_body))
        return model_kwargs

    def _run_agent(self, prompt: str, *, timeout: float) -> dict[str, Any]:
        key = resolve_api_key_value(self.api_key_env)
        base = resolve_base_url(self.base_url)
        if not key and not is_http_loopback(base):
            raise ExtensionMaterializeError(
                f"miniswe_missing_credential: env {self.api_key_env or 'OPENAI_API_KEY'!r} unset",
                kind="extension_materialize_failed",
            )
        try:
            from minisweagent.agents.default import DefaultAgent
            from minisweagent.models.litellm_model import LitellmModel
        except ImportError as exc:
            raise ExtensionMaterializeError(
                "miniswe_package_missing: install mini-swe-agent via "
                "uv tool install 'ageval-cli[miniswe]' (repo checkout: uv sync --extra miniswe)",
                kind="extension_materialize_failed",
            ) from exc
        model_kwargs = self._litellm_model_kwargs(key=key, base=base)
        official = _load_official_mini_config()
        agent_cfg = official.get("agent") if isinstance(official.get("agent"), dict) else {}
        model_cfg = official.get("model") if isinstance(official.get("model"), dict) else {}
        obs = model_cfg.get("observation_template")
        fmt = model_cfg.get("format_error_template")
        model = LitellmModel(
            model_name=self.model,
            model_kwargs=model_kwargs,
            cost_tracking="ignore_errors",
            **({} if not obs else {"observation_template": obs}),
            **({} if not fmt else {"format_error_template": fmt}),
        )
        env = self._make_env()
        system_template = str(agent_cfg.get("system_template") or "")
        instance_template = str(agent_cfg.get("instance_template") or "")
        if not system_template or not instance_template:
            raise ExtensionMaterializeError(
                "miniswe_config_missing: official mini.yaml has no agent templates",
                kind="extension_materialize_failed",
            )
        stall = current_stall()
        agent = DefaultAgent(
            model,
            env,
            system_template=system_template,
            instance_template=instance_template,
            step_limit=self.step_limit,
            cost_limit=self.cost_limit,
            wall_time_limit_seconds=0 if stall is not None else max(0, int(timeout)),
        )
        model.query = wrap_model_query(model.query, stall)
        wait = max(1.0, float(timeout))

        def _go() -> dict[str, Any]:
            if stall is not None:
                stall.claim()
            restore_retry = install_single_package_attempt()
            try:
                result = agent.run(prompt)
            finally:
                restore_retry()
            payload = {
                "exit_status": result.get("exit_status") if isinstance(result, dict) else "",
                "submission": result.get("submission") if isinstance(result, dict) else "",
                "messages": list(agent.messages),
                "n_calls": agent.n_calls,
                "cost": agent.cost,
            }
            if isinstance(result, dict) and result.get("exit_status") == "Submitted":
                payload["exit_content"] = str(
                    result.get("submission") or result.get("content") or ""
                )
            return payload

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_go)
            try:
                if stall is None:
                    return fut.result(timeout=wait)
                return wait_excluding_stall(fut, stall, wait)
            except concurrent.futures.TimeoutError as exc:
                raise TimeoutError("miniswe_timeout") from exc


def build_executor(
    *,
    host: Any,
    placement: Any,
    options: dict[str, Any] | None = None,
    profile_id: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    package_root: str | None = None,
) -> MinisweExecutorSPI:
    """plugin.yaml exclusive entry: factory receives host + placement from bind_winner."""
    del package_root
    return MinisweExecutorSPI(
        host=host,
        placement=placement,
        options=options,
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
