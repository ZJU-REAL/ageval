"""Agent-box egress_allowlist unions bound base_url hosts with authored extras."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from ageval.application.run import _egress_allowlist
from ageval.config.model import LockedTaskConfig


def test_agent_allowlist_unions_extras_not_scoring_extras() -> None:
    lock = SimpleNamespace(
        agent_profiles=[
            {"id": "solver", "base_url": "https://solver.example.com/v1"},
            {"id": "judge", "base_url": "https://api.judge.example.com/v1"},
        ],
        job_overlay={
            "environment_options": {
                "egress": "llm",
                "egress_allow": ["registry.npmjs.org"],
            },
            "evaluate_host": {
                "environment_options": {
                    "egress": "llm",
                    "egress_allow": ["extra.judge.example.com"],
                },
            },
        },
    )
    assert _egress_allowlist(cast(LockedTaskConfig, lock)) == [
        "api.judge.example.com",
        "registry.npmjs.org",
        "solver.example.com",
    ]


def test_agent_allowlist_omit_extras_is_derived_hosts_only() -> None:
    lock = SimpleNamespace(
        agent_profiles=[{"id": "solver", "base_url": "https://solver.example.com/v1"}],
        job_overlay={"environment_options": {"egress": "llm"}},
    )
    assert _egress_allowlist(cast(LockedTaskConfig, lock)) == ["solver.example.com"]
