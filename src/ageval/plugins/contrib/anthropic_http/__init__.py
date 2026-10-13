"""anthropic-http first-party executor (Anthropic Messages API)."""

from __future__ import annotations

from typing import Any

from ageval.plugins.contrib.anthropic_http.executor import AnthropicHTTPExecutor
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.slots import EXECUTOR

PLUGIN_ID = "anthropic-http"
PRIORITY = 120


def build_anthropic_http_executor(**kwargs: Any) -> AnthropicHTTPExecutor:
    """Bind the ``executor`` slot for Anthropic Messages (no box needed)."""
    return AnthropicHTTPExecutor(**kwargs)


def register_anthropic_http_contrib(registry: ExtensionRegistry) -> None:
    registry.exclusive(
        EXECUTOR,
        PLUGIN_ID,
        AnthropicHTTPExecutor,
        priority=PRIORITY,
        source="first-party",
        is_factory=True,
    )


__all__ = ["PLUGIN_ID", "register_anthropic_http_contrib"]
