"""Unit tests for executor inventory (ACP + openai-http)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.plugins.executor_inventory import (
    build_executor_inventory,
    describe_acp_entry,
    describe_executor,
    probe_binary,
)


def test_probe_binary_first_hit() -> None:
    def fake_which(name: str) -> str | None:
        return {"pi": "/usr/bin/pi"}.get(name)

    name, path = probe_binary(("pi", "pi-agent"), which=fake_which)
    assert name == "pi"
    assert path == "/usr/bin/pi"


def test_probe_binary_miss() -> None:
    name, path = probe_binary(("nope-cli",), which=lambda _n: None)
    assert name == "nope-cli"
    assert path is None


def test_describe_acp_kind() -> None:
    row = describe_executor("acp", which=lambda _n: None, verbose=False)
    assert row["kind"] == "acp"
    assert row["execution_mode"] == "acp-stdio"


def test_describe_api_client_no_binary() -> None:
    row = describe_executor("openai-http", which=lambda _n: None, verbose=True)
    assert row["execution_mode"] == "api-client"
    assert row["binary_on_path"] is None
    assert row["host_ready"] is True
    assert row["tools"] == "native"
    assert row["session"] == "new-only"
    anthropic = describe_executor("anthropic-http", which=lambda _n: None, verbose=True)
    assert anthropic["execution_mode"] == "api-client"
    assert anthropic["host_ready"] is True
    assert anthropic["tools"] == "native"


def test_describe_acp_entry_adapter_missing() -> None:
    def which(name: str) -> str | None:
        if name == "codex":
            return "/fake/codex"
        return None

    row = describe_acp_entry("codex", which=which, verbose=True)
    assert row["readiness"] == "adapter-missing"
    assert row["engine_ready"] is True
    assert row["acp_entry_ready"] is False
    assert "install_command" in row
    assert row["runtime"] == {"node": ">=16.0.0"}


def test_plugin_without_describe_is_not_host_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ageval.plugins.store import install_from_path

    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry

    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "plugins" / "sample-echo"
    install_from_path(fixture)
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()

    row = describe_executor("sample-echo", which=lambda _n: None, verbose=True)
    assert row["execution_mode"] == "unknown"
    assert row["host_ready"] is False
    assert row["bake_recipe_declared"] is False
    assert row["binary_on_path"] is None


def test_plugin_host_ready_uses_host_requires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ageval.plugins.store import install_from_path

    home = tmp_path / "ageval-home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.registry import reset_global_registry

    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "plugins" / "host-probe"
    install_from_path(fixture)
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()

    row = describe_executor("host-probe", which=lambda _n: "/bin/host-probe-bin", verbose=True)
    assert row["execution_mode"] == "container-worker"
    assert row["host_ready"] is False
    assert row["bake_recipe_declared"] is True
    assert row["binary"] == "host-probe-bin"
    assert row["binary_on_path"] is None
    assert row["binary_path"] is None

    (tmp_path / "host_probe_vendor_sdk.py").write_text("ok = True\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib

    importlib.invalidate_caches()
    ready = describe_executor("host-probe", which=lambda _n: None, verbose=False)
    assert ready["host_ready"] is True


def test_inventory_aggregates() -> None:
    def fake_which(name: str) -> str | None:
        return {
            "codex": "/bin/codex",
            "codex-acp": "/bin/codex-acp",
            "opencode": "/bin/opencode",
        }.get(name)

    inv = build_executor_inventory(which=fake_which, verbose=False)
    assert "acp" in inv["supported"]
    assert "openai-http" in inv["supported"]
    assert "codex" not in inv["supported"]
    entry_ids = {r["entry_id"] for r in inv["acp_entries"]}
    assert "codex" in entry_ids
    assert "required_v014" not in inv
