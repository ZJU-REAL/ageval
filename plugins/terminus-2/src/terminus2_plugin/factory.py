"""terminus-2 ExecutorSPI. The model stays on the parent. tmux stays in the box."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ageval.environments.protocol import EnvironmentFailure
from ageval.model import ModelConfigError, ModelSpec, require_model_support, spec_from_factory
from ageval.model.usage import NOT_REPORTED, adopt_usage
from ageval.plugins.agent_result import AgentResult
from ageval.plugins.base import BaseExecutor
from ageval.plugins.decorators import executor_plugin
from ageval.plugins.errors import ExtensionMaterializeError
from ageval.plugins.http_loopback import is_http_loopback
from ageval.plugins.options import coerce_options, mapping_for_model
from terminus2_plugin import PLUGIN_ID
from terminus2_plugin.episode import run_episode
from terminus2_plugin.model_client import ModelReply, StallExhausted, TransportFailure, complete
from terminus2_plugin.options import Terminus2Options
from terminus2_plugin.tmux import TmuxSession

_CREDENTIAL_ENV_NAMES = ("OPENAI_API_KEY", "litellm_api_key", "LITELLM_API_KEY")
_BASE_URL_ENV_FALLBACKS = ("OPENAI_BASE_URL", "litellm_base_url", "LITELLM_BASE_URL")
_DEFAULT_MODEL_ID = "openai/gpt-4o-mini"


def describe_terminus2() -> dict[str, Any]:
    return {
        "execution_mode": "host-loop",
        "tools": "adapter-loop",
        "structured_output": "validated-text",
        "session": "one-shot",
        "stream": "synthetic-lifecycle",
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
        value = os.environ.get(name)
        if value and str(value).strip():
            return str(value).strip()
    return None


def resolve_base_url(explicit: str | None) -> str | None:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for key in _BASE_URL_ENV_FALLBACKS:
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()
    return None


def _write_backend_raw(collect_dir: str | None, payload: dict[str, Any]) -> None:
    if not collect_dir:
        return
    root = Path(collect_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "terminus-2.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2) + "\n",
        encoding="utf-8",
    )


@executor_plugin(priority=110, source="installed")
class Terminus2ExecutorSPI(BaseExecutor):
    """Host loop over a bound ModelSpec. Shell I/O is tmux inside the environment."""

    kind = PLUGIN_ID
    requires_environment = True
    supported_apis = frozenset({"chat", "responses"})
    supported_model_fields = frozenset(
        {"id", "api", "reasoning_effort", "timeout", "watchdog", "extra"}
    )
    extra_allowlist = frozenset({"reasoning", "provider"})
    Options = Terminus2Options

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
        spec = spec_from_factory(model, raw, default_id=_DEFAULT_MODEL_ID)
        self.supports_model(spec)
        self.bind_model(spec)
        parsed = (
            options
            if isinstance(options, Terminus2Options)
            else coerce_options(Terminus2Options, raw)
        )
        self.options = parsed
        self.base_url = base_url if isinstance(base_url, str) else None
        self.api_key_env = api_key if isinstance(api_key, str) else None
        self.session_id = f"ageval-{self.profile_id or 'solver'}-{uuid.uuid4().hex[:12]}"
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

    @staticmethod
    def describe() -> dict[str, Any]:
        return describe_terminus2()

    def open(self, **kwargs: Any) -> None:
        del kwargs
        if _offline():
            raise ExtensionMaterializeError("offline_forced", kind="extension_materialize_failed")
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
        del redaction_sentinels, tools, messages
        if _offline():
            return self._failed("offline_forced", repeatable=False)
        if self.host is None:
            return self._failed("terminus2_environment_missing", repeatable=False)
        try:
            episode = self._run(prompt, timeout=timeout, workdir=workdir, collect_dir=collect_dir)
        except StallExhausted as exc:
            return self._failed("stall_exhausted", repeatable=False, detail=exc.code)
        except TransportFailure as exc:
            return self._failed(exc.code, repeatable=True)
        except ModelConfigError as exc:
            return self._failed(str(exc), repeatable=True)
        except EnvironmentFailure as exc:
            return self._failed(exc.message, repeatable=False)
        except ExtensionMaterializeError as exc:
            return self._failed(str(getattr(exc, "message", None) or exc), repeatable=False)
        usage = adopt_usage(episode.usage or None)
        if usage is NOT_REPORTED and not episode.usage:
            usage = NOT_REPORTED
        return AgentResult(
            model=self.model,
            text=episode.text,
            structured=None,
            ok=episode.ok,
            error=episode.error,
            events=episode.events,
            usage=usage,
            repeatable=not episode.keys_sent,
            metadata=self._metadata(turns=episode.raw.get("turns")),
        )

    def _run(
        self,
        prompt: str,
        *,
        timeout: float,
        workdir: str | None,
        collect_dir: str | None,
    ):
        key = resolve_api_key_value(self.api_key_env)
        base = resolve_base_url(self.base_url)
        if not key and not is_http_loopback(base):
            missing = self.api_key_env or "OPENAI_API_KEY"
            raise ExtensionMaterializeError(
                f"terminus2_missing_credential:{missing}",
                kind="extension_materialize_failed",
            )
        if not base:
            raise ModelConfigError("terminus2_base_url_missing")
        cwd = workdir or str(getattr(self.placement, "workdir", None) or "/attempt/workspace")
        user = getattr(self.placement, "user", None)
        session = TmuxSession(
            self.host,
            session_name=_tmux_name(self),
            cwd=cwd,
            user=str(user) if user else None,
            pane_width=self.options.pane_width,
            pane_height=self.options.pane_height,
            cmd_timeout=float(self.options.cmd_timeout),
        )

        def model(messages: list[dict[str, Any]]) -> ModelReply:
            return complete(
                messages,
                spec=self.spec,
                api_key=key,
                base_url=base,
                invoke_timeout=timeout,
            )

        from ageval.plugins.step_activity import scope_of

        scope = scope_of(self)
        episode = run_episode(
            instruction=prompt,
            session=session,
            model=model,
            parser=self.options.parser,
            step_limit=self.options.step_limit,
            max_format_errors=self.options.max_format_errors,
            timeout=timeout,
            session_id=self.session_id,
            activity=scope,
            reuse_session=bool(scope and scope.environment_reattached),
        )
        _write_backend_raw(collect_dir, episode.raw)
        return episode

    def _failed(
        self,
        error: str,
        *,
        repeatable: bool,
        detail: str | None = None,
    ) -> AgentResult:
        metadata = self._metadata()
        if detail:
            metadata["error_detail"] = detail
        return AgentResult(
            model=getattr(self, "model", ""),
            text="",
            structured=None,
            ok=False,
            error=error,
            repeatable=repeatable,
            metadata=metadata,
        )

    def _metadata(self, turns: Any = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "plugin": PLUGIN_ID,
            "session_id": self.session_id,
            "api": self.api,
            "parser": self.options.parser,
            "locked_reasoning_effort": self.reasoning_effort,
            "actual_reasoning_effort": self.reasoning_effort,
            "execution_location": getattr(self.host, "kind", None) or "box",
        }
        if turns is not None:
            metadata["turns"] = turns
        return metadata


def _tmux_name(executor: Terminus2ExecutorSPI) -> str:
    from ageval.plugins.step_activity import scope_of

    scope = scope_of(executor)
    if scope is None:
        return "t" + uuid.uuid4().hex[:8]
    digest = hashlib.sha256(scope.invoke_request_id.encode()).hexdigest()[:8]
    return "t" + digest


def build_executor(**kwargs: Any) -> Terminus2ExecutorSPI:
    kwargs.pop("package_root", None)
    return Terminus2ExecutorSPI(**kwargs)


__all__ = ["Terminus2ExecutorSPI", "build_executor", "describe_terminus2"]
