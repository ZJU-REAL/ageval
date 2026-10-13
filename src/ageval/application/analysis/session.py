"""Bind an existing HTTP agent against a fresh local environment.

The wrapper is a real ``environment: local`` box. Analysis never writes the
sealed evidence tree. Credentials stay on the agent package locators.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ageval.agents.manifest import load_agent_manifest
from ageval.agents.reserved import builtin_harness_root, canonical_harness_id
from ageval.application.analysis.errors import ANALYSIS_AGENT
from ageval.config.env_refs import is_http_url
from ageval.config.errors import ConfigError
from ageval.config.profiles import model_id
from ageval.environments.protocol import BoxSpec, EnvironmentFailure
from ageval.plugins.binding import bind_winner
from ageval.plugins.bootstrap import ensure_bootstrapped
from ageval.plugins.errors import ExtensionRegistryError
from ageval.plugins.services import ServiceTable
from ageval.plugins.slots import ENVIRONMENT
from ageval.runtime.agent_binding import AgentBinder

_HTTP_EXECUTORS = frozenset({"openai-http", "anthropic-http"})


@dataclass
class BoundAnalysisAgent:
    """One live HTTP executor and the local box it is bound to."""

    executor: Any
    executor_kind: str
    model: str
    host: Any


def load_analysis_profile(
    agent: str,
    *,
    model: str | None,
    base_url: str | None,
) -> dict[str, Any]:
    """One synthetic profile row. Executor must already be an HTTP kind."""
    text = agent.strip()
    if not text:
        raise ConfigError(ANALYSIS_AGENT, "--agent is required", location="--agent")
    path = Path(text).expanduser()
    if path.exists():
        manifest = load_agent_manifest(path)
    else:
        harness = canonical_harness_id(text)
        if harness is None:
            raise ConfigError(
                ANALYSIS_AGENT,
                f"unknown analysis agent {text!r}",
                location="--agent",
            )
        manifest = load_agent_manifest(builtin_harness_root(harness))
    binding = deepcopy(manifest.binding)
    executor = str(binding.get("executor") or "")
    if executor not in _HTTP_EXECUTORS:
        raise ConfigError(
            ANALYSIS_AGENT,
            f"analysis agent {text!r} uses executor {executor!r}; "
            "only openai-http and anthropic-http are allowed",
            location="--agent",
        )
    row = dict(binding)
    row["id"] = "analyst"
    if isinstance(model, str) and model.strip():
        current = row.get("model")
        if isinstance(current, Mapping):
            updated = dict(current)
            updated["id"] = model.strip()
            row["model"] = updated
        else:
            row["model"] = {"id": model.strip()}
    if not model_id(row.get("model")):
        raise ConfigError(
            ANALYSIS_AGENT,
            "--model is required when the agent binding has no model",
            location="--model",
        )
    if isinstance(base_url, str) and base_url.strip():
        url = base_url.strip()
        if not is_http_url(url):
            raise ConfigError(
                ANALYSIS_AGENT,
                "--base-url must be an http(s) URL",
                location="--base-url",
            )
        row["base_url"] = url
    return row


@asynccontextmanager
async def analysis_agent(
    dataset_root: Path,
    agent: str,
    *,
    model: str | None,
    base_url: str | None,
) -> AsyncIterator[BoundAnalysisAgent]:
    """Open one local box and bind ``agent`` for a single analysis pass."""
    row = load_analysis_profile(agent, model=model, base_url=base_url)
    wrapper = Path(tempfile.mkdtemp(prefix="ageval-analysis-"))
    host: Any = None
    try:
        try:
            registry = ensure_bootstrapped()
            services = ServiceTable()
            binder = AgentBinder(
                profiles=(row,),
                services=services,
                registry=registry,
                environment="local",
                task_root=dataset_root,
            )
            graph = binder.graph("analyst")
            host = bind_winner(
                registry,
                graph,
                ENVIRONMENT,
                spec=BoxSpec(
                    attempt_root=wrapper,
                    task_root=dataset_root,
                    repo_root=dataset_root,
                ),
            )
            await host.preflight()
            await host.start()
            winner = graph.winners[ENVIRONMENT]
            services.register(ENVIRONMENT, host, plugin_id=winner.plugin_id)
            bound = binder.bind("analyst")
            yield BoundAnalysisAgent(
                executor=bound.executor,
                executor_kind=str(getattr(bound.executor, "kind", bound.plugin_id)),
                model=bound.model,
                host=host,
            )
        except ConfigError:
            raise
        except (EnvironmentFailure, ExtensionRegistryError) as exc:
            raise ConfigError(ANALYSIS_AGENT, str(exc), location="--agent") from exc
    finally:
        if host is not None:
            with contextlib.suppress(EnvironmentFailure, OSError):
                await host.stop(delete=True)
        if wrapper.exists():
            shutil.rmtree(wrapper, ignore_errors=True)
