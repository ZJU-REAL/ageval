"""ageval_sdk — optional task SDK surface for dataset task authors.

Does not own Run identity, Provider, credentials, or final PASS.
"""

from __future__ import annotations

from pathlib import Path

from ageval_sdk.agent import Agent, AgentSession
from ageval_sdk.context import RunContext, RunParameterView, RunScope
from ageval_sdk.evaluation import evaluation_check
from ageval_sdk.terminal import RunTerminal
from ageval_sdk.tool import AllowList, CallLimit, Tool, ToolSet
from ageval_sdk.workflow import bounded_gather, collect_results, first_success


def _load_version() -> str:
    try:
        from importlib.metadata import version

        return version("ageval-cli")
    except Exception:
        pass
    # Editable / source tree: repo-root VERSION (src/ageval_sdk/__init__.py → parents[2]).
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


__all__ = [
    "Agent",
    "AgentSession",
    "AllowList",
    "CallLimit",
    "RunContext",
    "RunParameterView",
    "RunTerminal",
    "RunScope",
    "Tool",
    "ToolSet",
    "bounded_gather",
    "collect_results",
    "first_success",
    "evaluation_check",
]

__version__ = _load_version()
