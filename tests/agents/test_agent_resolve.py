"""--agent spec parsing + projection into the profiles lane (design/14)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ageval.application.agent_ops.resolve import (
    bindings_from_agent_specs,
    parse_agent_spec,
    resolve_agent_specs,
)
from ageval.config.errors import ConfigError


@pytest.fixture(autouse=True)
def _ageval_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ageval-home"
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    return home


def _make_pkg(tmp_path: Path, agent_id: str = "http-default", version: str = "0.1.0") -> Path:
    pkg = tmp_path / f"pkg-{agent_id}-{version}"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "agent.yaml").write_text(
        f"format: ageval.agent/1\nagent_id: {agent_id}\nversion: '{version}'\n"
        "label: T\nbinding: {executor: openai-http, model: {id: none}}\n",
        encoding="utf-8",
    )
    return pkg


def test_parse_agent_spec_forms() -> None:
    assert parse_agent_spec("local/x@1.0") == ("*", "local/x@1.0")
    assert parse_agent_spec("solver=local/x@1.0") == ("solver", "local/x@1.0")
    assert parse_agent_spec("./dir/agent.yaml") == ("*", "./dir/agent.yaml")
    # '=' inside a ref that is not a role assignment stays whole
    assert parse_agent_spec("solver=./p/agent.yaml") == ("solver", "./p/agent.yaml")
    with pytest.raises(ConfigError):
        parse_agent_spec("  ")


def test_bindings_from_path_spec(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    agent_profiles = bindings_from_agent_specs([str(pkg)])
    assert set(agent_profiles) == {"*"}
    row = agent_profiles["*"]
    assert row["executor"] == "openai-http"
    assert row["agent_ref"].startswith("file:")
    assert "+sha256:" in row["agent_ref"]


def test_bindings_from_cache_ref_with_local_fallback(tmp_path: Path) -> None:
    from ageval.agents.store import install_from_path

    install_from_path(_make_pkg(tmp_path))
    for ref in ("local/http-default@0.1.0", "http-default@0.1.0"):
        agent_profiles = bindings_from_agent_specs([f"solver={ref}"])
        assert agent_profiles["solver"]["agent_ref"].startswith("local/http-default@0.1.0+sha256:")


def test_both_installed_versions_project(tmp_path: Path) -> None:
    from ageval.agents.store import install_from_path

    install_from_path(_make_pkg(tmp_path, version="1.0.0"))
    install_from_path(_make_pkg(tmp_path, version="2.0.0"))
    b1 = bindings_from_agent_specs(["local/http-default@1.0.0"])
    b2 = bindings_from_agent_specs(["local/http-default@2.0.0"])
    assert b1["*"]["agent_ref"].startswith("local/http-default@1.0.0+sha256:")
    assert b2["*"]["agent_ref"].startswith("local/http-default@2.0.0+sha256:")


def test_missing_cache_ref_fails_closed() -> None:
    with pytest.raises(ConfigError):
        bindings_from_agent_specs(["ghost@1.0"])


def test_bindings_from_builtin_short_id() -> None:
    agent_profiles = bindings_from_agent_specs(["pi"])
    row = agent_profiles["*"]
    assert row["executor"] == "acp"
    assert "model" not in row
    assert row["agent_ref"].startswith("pi@0.1.0+sha256:")
    opencode = bindings_from_agent_specs(["opencode"])["*"]
    assert opencode["overlays"] == ["overlays/opencode.litellm.json"]
    assert opencode["agent_ref"].startswith("opencode@0.1.0+sha256:")


def test_builtin_model_override() -> None:
    out = resolve_agent_specs(["pi"], model="glm-4.7")
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert [row["model"] for row in doc["agent_profiles"].values()] == [{"id": "glm-4.7"}]
    assert {row["agent_ref"].split("@", 1)[0] for row in doc["agent_profiles"].values()} == {"pi"}


def test_duplicate_role_fails_closed(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    with pytest.raises(ConfigError):
        bindings_from_agent_specs([str(pkg), str(pkg)])
    with pytest.raises(ConfigError):
        bindings_from_agent_specs([f"solver={pkg}", f"solver={pkg}"])


def test_resolve_writes_parseable_profiles_document(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    out = resolve_agent_specs([str(pkg), f"critic={pkg}"])
    assert out.is_file()
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["format"] == "ageval.profiles/1"
    assert set(doc["agent_profiles"]) == {"*", "critic"}
    # Content-addressed: same specs → same path.
    assert resolve_agent_specs([str(pkg), f"critic={pkg}"]) == out


def test_resolve_model_overrides_bound_roles(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    default = resolve_agent_specs([str(pkg), f"critic={pkg}"])
    overridden = resolve_agent_specs([str(pkg), f"critic={pkg}"], model="glm-4.7")
    assert overridden != default
    doc = yaml.safe_load(overridden.read_text(encoding="utf-8"))
    models = [row["model"] for row in doc["agent_profiles"].values()]
    assert models == [{"id": "glm-4.7"}] * len(models)
    base = yaml.safe_load(default.read_text(encoding="utf-8"))
    base_models = [row["model"] for row in base["agent_profiles"].values()]
    assert base_models == [{"id": "none"}] * len(base_models)
