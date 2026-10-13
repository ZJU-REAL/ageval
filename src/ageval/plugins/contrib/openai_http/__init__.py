"""openai-http first-party executor provide (API client path)."""

from __future__ import annotations

from typing import Any

from ageval.plugins.contrib.openai_http.executor import OpenAIHTTPExecutor
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.slots import EXECUTOR

PLUGIN_ID = "openai-http"
PRIORITY = 120


def build_openai_http_executor(**kwargs: Any) -> OpenAIHTTPExecutor:
    """Bind the ``executor`` slot for a plain HTTP API backend (no box needed)."""
    return OpenAIHTTPExecutor(**kwargs)


def register_openai_http_contrib(registry: ExtensionRegistry) -> None:
    registry.exclusive(
        EXECUTOR,
        PLUGIN_ID,
        OpenAIHTTPExecutor,
        priority=PRIORITY,
        source="first-party",
        is_factory=True,
    )


__all__ = ["PLUGIN_ID", "register_openai_http_contrib"]
