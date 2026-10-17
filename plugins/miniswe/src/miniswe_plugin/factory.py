"""miniswe ExecutorSPI — host mini-swe-agent loop, bash via environment.exec."""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.model import ModelSpec, require_model_support, spec_from_factory
from ageval.plugins.agent_result import AgentResult, parse_validated_text_structured
from ageval.plugins.base import BaseExecutor
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.http_loopback import is_http_loopback
from ageval.plugins.options import coerce_options, mapping_for_model
from ageval.runtime.upstream_stall import current_stall
from miniswe_plugin import PLUGIN_ID
from miniswe_plugin.env import ProtocolEnv
from miniswe_plugin.llm_client import (
    bind_direct_completion_client,
    bind_direct_responses_client,
    chat_model_for_openai_compat_gateway,
)
from miniswe_plugin.model import DEFAULT_MODEL_ID, transport_clocks, wire_body
from miniswe_plugin.options import MinisweOptions
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


def describe_miniswe() -> dict[str, Any]:
    return {
        "execution_mode": "host-loop",
        "tools": "bash",
        "structured_output": "validated-text",
        "session": "one-shot",
        "stream": "chat-sse-default",
        "credential_env_names": _CREDENTIAL_ENV_NAMES,
        "binary": "",
    }


def _offline() -> bool:
    return os.environ.get("AGEVAL_OFFLINE_AGENT") == "1"


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
    """Optional minisweagent config roots. A missing package falls through to vendor."""
    roots: list[Path] = []
    with contextlib.suppress(Exception):
        import minisweagent

        roots.append(Path(minisweagent.package_dir) / "config")
        roots.append(Path(minisweagent.__file__).resolve().parent / "config")
    with contextlib.suppress(Exception):
        from importlib.resources import files

        roots.append(Path(str(files("minisweagent").joinpath("config"))))
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


@executor_plugin(priority=110, source="installed")
class MinisweExecutorSPI(BaseExecutor):
    """Executor SPI. The box runs the shell; the LLM client stays on this side."""

    kind = PLUGIN_ID
    requires_environment = True
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset(
        {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
    )
    extra_allowlist = frozenset({"reasoning", "provider"})
    Options = MinisweOptions

    def __init__(
        self,
        *,
        host: Any,
        placement: Any,
        options: dict[str, Any] | None = None,
        profile_id: str | None = None,
        model: Any = None,
        base_url: str | None = None,
        api_key: str | None = None,
        plugin_id: str | None = None,
        **_kwargs: Any,
    ) -> None:
        del plugin_id
        raw = mapping_for_model(options)
        self.host = host
        self.placement = placement
        self.profile_id = profile_id
        spec = spec_from_factory(model, raw, default_id=DEFAULT_MODEL_ID)
        self.supports_model(spec)
        self.bind_model(spec)
        parsed = (
            options if isinstance(options, MinisweOptions) else coerce_options(MinisweOptions, raw)
        )
        self.options = parsed
        self.base_url = base_url if isinstance(base_url, str) else None
        self.api_key_env = api_key if isinstance(api_key, str) else None
        self.step_limit = parsed.step_limit
        self.cost_limit = parsed.cost_limit
        self.cmd_timeout = parsed.cmd_timeout
        # Chat Completions default to SSE streaming; Responses ignores this.
        self.stream = parsed.stream if self.api == "chat" else None
        self.session_id = f"ageval-{self.profile_id or 'solver'}-{uuid.uuid4().hex[:12]}"
        self.execution_location = getattr(host, "kind", None) or "box"
        self._ready = False

    @classmethod
    def supports_model(cls, spec: ModelSpec) -> None:
        require_model_support(
            spec,
            supported_apis=cls.supported_apis,
            supported_model_fields=cls.supported_model_fields,
            extra_allowlist=cls.extra_allowlist,
        )

    def bind_model(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.model = spec.id
        self.reasoning_effort = spec.reasoning_effort
        self.api = spec.api
        self.extra_body = dict(spec.extra)
        # Both clocks are filled from the table when the spec omits them.
        self.timeout, self.watchdog = transport_clocks(spec)

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
        tools: Sequence[Mapping[str, Any]] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> AgentResult:
        del redaction_sentinels, workdir, tools, messages
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
            "api": self.api,
            "chat_stream": self.stream,
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
        # Unset effort and timeout stay absent. extra cannot carry those keys.
        model_kwargs.update(wire_body(self.spec))
        # Force Connection: close on the wire so gateways / httpx do not keep a
        # sticky ESTAB that later turns hang on (_receive_response_headers +
        # large Send-Q). Merged last over extra headers except we still
        # allow callers to add other headers alongside.
        raw_headers = model_kwargs.get("extra_headers")
        headers = dict(raw_headers) if isinstance(raw_headers, dict) else {}
        headers.setdefault("Connection", "close")
        model_kwargs["extra_headers"] = headers
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
        model_cls: type = LitellmModel
        if self.api == "responses":
            try:
                from minisweagent.models.litellm_response_model import LitellmResponseModel
            except ImportError as exc:
                raise ExtensionMaterializeError(
                    "miniswe_package_missing: LitellmResponseModel required "
                    "for options.api=responses",
                    kind="extension_materialize_failed",
                ) from exc
            model_cls = LitellmResponseModel
        model_kwargs = self._litellm_model_kwargs(key=key, base=base)
        official = _load_official_mini_config()
        agent_cfg = official.get("agent") if isinstance(official.get("agent"), dict) else {}
        model_cfg = official.get("model") if isinstance(official.get("model"), dict) else {}
        obs = model_cfg.get("observation_template")
        fmt = model_cfg.get("format_error_template")
        # Chat against OpenAI-compat gateways: remap anthropic/ (etc.) so LiteLLM
        # uses /v1/chat/completions with the original id on the wire. Raw
        # anthropic/ makes LiteLLM take the Messages SDK path → 404 / crash →
        # upstream_stall forever (curl chat still 200). Responses keeps profile id.
        litellm_model = (
            chat_model_for_openai_compat_gateway(self.model) if self.api == "chat" else self.model
        )
        model = model_cls(
            model_name=litellm_model,
            model_kwargs=model_kwargs,
            cost_tracking="ignore_errors",
            **({} if not obs else {"observation_template": obs}),
            **({} if not fmt else {"format_error_template": fmt}),
        )
        # Bypass litellm entirely for HTTP: sticky keep-alive + ignored timeouts
        # left suites hung in _receive_response_headers with no upstream_stall
        # (attempt_1c23ff53 ~4.5min). Both chat and responses use direct httpx.
        # ``self.timeout`` is the HTTP clock. Omit on the spec is the table default.
        if self.api == "responses":
            bind_direct_responses_client(
                model,
                api_key=key,
                api_base=base,
                timeout=self.timeout,
            )
        else:
            bind_direct_completion_client(
                model,
                api_key=key,
                api_base=base,
                timeout=self.timeout,
                stream=self.stream,
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
            # The parent stall freezes wall and phase clocks for the episode.
            # This package wall stays the parent invoke timeout, so a stuck
            # agent still ends. The Future watchdog is ``self.watchdog``.
            wall_time_limit_seconds=max(0, int(timeout)),
        )
        model.query = wrap_model_query(model.query, stall, watchdog=self.watchdog)
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


def build_executor(**kwargs: Any) -> MinisweExecutorSPI:
    """Thin wrapper. The installed entry is the class."""
    kwargs.pop("package_root", None)
    return MinisweExecutorSPI(**kwargs)
