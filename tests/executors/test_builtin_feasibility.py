"""ACP entry feasibility: offline paths + PATH readiness (no secret output)."""

from __future__ import annotations

import pytest
from tests.helpers.box import local_box

from ageval.environments.protocol import HOME_PATH, Placement
from ageval.plugins.contrib.acp import AcpExecutor
from ageval.plugins.contrib.acp.registry import get_entry, list_entry_ids, readiness_for
from ageval.plugins.executor_capabilities import BUILTIN_CAPABILITIES


def test_acp_offline_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGEVAL_OFFLINE_AGENT", "1")
    executor = AcpExecutor(
        host=local_box("/nowhere"),
        placement=Placement(target_id="unstarted", home=HOME_PATH),
        entry_id="opencode",
        model="entry-default",
    )
    r = executor.invoke("hi")
    assert r.ok is False
    assert r.error == "offline_forced"


def test_capability_credential_names_are_locators_only() -> None:
    for _kind, cap in BUILTIN_CAPABILITIES.items():
        for name in cap.credential_env_names:
            assert name.isupper() or "_" in name
            assert not name.startswith("sk-")
            assert "=" not in name
    for eid in list_entry_ids():
        desc = get_entry(eid)
        assert desc is not None
        for name in desc.credential_env_names:
            assert not name.startswith("sk-")


def test_five_acp_entries_registered() -> None:
    ids = set(list_entry_ids())
    assert {"codex", "claude-code", "pi", "opencode", "grok-build"} <= ids
    for eid in ids:
        row = readiness_for(get_entry(eid))  # type: ignore[arg-type]
        assert row["readiness"] in {
            "ready",
            "engine-missing",
            "adapter-missing",
            "entry-missing",
            "unsupported-platform",
        }
