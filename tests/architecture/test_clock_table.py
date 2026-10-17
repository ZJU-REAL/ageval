"""The clock table is the only place those numbers are defined."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.runtime.clocks import DISABLED, ClockError, clocks_snapshot, parse_clock

_GOLDEN = {
    "acp_home_cap": {
        "default": 120.0,
        "zero": "reject",
        "integral": False,
        "non_positive": False,
        "stall_freezes_parent": False,
        "readers": ["acp.executor", "acp.hooks"],
    },
    "docker_build": {
        "default": 3600.0,
        "zero": "reject",
        "integral": False,
        "non_positive": False,
        "stall_freezes_parent": False,
        "readers": ["docker.images"],
    },
    "idle_timeout": {
        "default": "disabled",
        "zero": "disabled",
        "integral": False,
        "non_positive": True,
        "stall_freezes_parent": False,
        "readers": ["acp"],
    },
    "invoke_timeout": {
        "default": 300.0,
        "zero": "fallback",
        "integral": False,
        "non_positive": True,
        "stall_freezes_parent": False,
        "readers": ["runtime.parent_agent"],
    },
    "stall_interval": {
        "default": 60.0,
        "zero": "reject",
        "integral": True,
        "non_positive": False,
        "stall_freezes_parent": False,
        "readers": ["runtime.upstream_stall"],
    },
    "timeout": {
        "default": "disabled",
        "zero": "disabled",
        "integral": False,
        "non_positive": False,
        "stall_freezes_parent": False,
        "readers": ["model.spec"],
    },
    "upstream_stall": {
        "default": 3600.0,
        "zero": "disabled",
        "integral": True,
        "non_positive": False,
        "stall_freezes_parent": True,
        "readers": ["runtime.upstream_stall"],
    },
    "watchdog": {
        "default": 180.0,
        "zero": "reject",
        "integral": False,
        "non_positive": False,
        "stall_freezes_parent": False,
        "readers": ["anthropic-http", "miniswe", "openai-http"],
    },
}

_BANNED = (
    "DEFAULT_WATCHDOG_SECONDS",
    "_DEFAULT_WATCHDOG_SECONDS",
    "DEFAULT_INVOKE_TIMEOUT_SECONDS",
    "UPSTREAM_STALL_DEFAULT_SECONDS",
    "UPSTREAM_STALL_INTERVAL_SECONDS",
)


def test_clocks_snapshot_matches_the_golden() -> None:
    assert clocks_snapshot() == _GOLDEN


def test_zero_watchdog_does_not_become_the_default() -> None:
    with pytest.raises(ClockError):
        parse_clock("watchdog", 0)
    assert parse_clock("watchdog", None) == 180.0
    assert parse_clock("timeout", 0) is DISABLED
    assert parse_clock("timeout", None) is DISABLED
    assert parse_clock("invoke_timeout", 0) == 300.0
    assert parse_clock("invoke_timeout", -1) == 300.0


def test_clock_constants_are_not_redefined() -> None:
    root = Path(__file__).resolve().parents[2]
    hits: list[str] = []
    for base in (root / "src", root / "plugins"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in _BANNED:
                if name in text:
                    hits.append(f"{path.relative_to(root)}:{name}")
    assert hits == []
