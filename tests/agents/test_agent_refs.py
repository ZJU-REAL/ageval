"""Parse agent_ref → Agent package root (design/14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.agents import store
from ageval.agents.refs import package_root_from_agent_ref, published_agent_ref_parts
from ageval.config.errors import ConfigError
from ageval.plugins.store import compute_tree_digest


@pytest.fixture(autouse=True)
def _ageval_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ageval-home"
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    return home


def _make_pkg(tmp_path: Path, agent_id: str = "http-default", version: str = "0.1.0") -> Path:
    pkg = tmp_path / f"pkg-{agent_id.replace('/', '-')}"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "agent.yaml").write_text(
        f"format: ageval.agent/1\nagent_id: {agent_id.rsplit('/', 1)[-1]}\nversion: '{version}'\n"
        "binding: {executor: openai-http, model: {id: none}}\n",
        encoding="utf-8",
    )
    return pkg


def test_published_agent_ref_parts() -> None:
    assert published_agent_ref_parts("official/http-default@0.1.0+sha256:aaaaaaaaaaaa") == (
        "official/http-default",
        "0.1.0",
    )
    assert published_agent_ref_parts("local/http-default@0.1.0+sha256:aaaaaaaaaaaa") is None
    assert published_agent_ref_parts("file:/tmp/agent@dev+sha256:aaaaaaaaaaaa") is None
    assert published_agent_ref_parts("pi@0.1.0+sha256:aaaaaaaaaaaa") is None
    assert published_agent_ref_parts(None) is None


def test_builtin_ref_resolves_shipped_tree() -> None:
    from ageval.agents.reserved import builtin_harness_root
    from ageval.plugins.store import compute_tree_digest

    root = builtin_harness_root("opencode")
    digest = compute_tree_digest(root)
    short = digest[len("sha256:") :][:12]
    resolved = package_root_from_agent_ref(f"opencode@0.1.0+sha256:{short}")
    assert resolved == root
    assert (resolved / "overlays" / "opencode.litellm.json").is_file()
    with pytest.raises(ConfigError) as ei:
        package_root_from_agent_ref("opencode@0.1.0+sha256:ffffffffffff")
    assert ei.value.error_code == "invalid_package"


def test_file_ref_resolves_directory(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    digest = compute_tree_digest(pkg)
    short = digest[len("sha256:") :][:12]
    root = package_root_from_agent_ref(f"file:{pkg}@dev+sha256:{short}")
    assert root == pkg.resolve()


def test_file_ref_resolves_agent_yaml(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    yaml_path = pkg / "agent.yaml"
    root = package_root_from_agent_ref(f"file:{yaml_path}@dev")
    assert root == pkg.resolve()


def test_file_ref_yaml_with_overlays_shares_package_root(tmp_path: Path) -> None:
    from ageval.agents.manifest import load_agent_manifest

    pkg = _make_pkg(tmp_path)
    yaml_path = pkg / "agent.yaml"
    yaml_path.write_text(
        "format: ageval.agent/1\nagent_id: http-default\nversion: '0.1.0'\n"
        "binding:\n  executor: openai-http\n  model: {id: none}\n"
        "  overlays: [overlays/skills/demo]\n",
        encoding="utf-8",
    )
    skill = pkg / "overlays" / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# demo\n", encoding="utf-8")
    manifest = load_agent_manifest(yaml_path)
    assert manifest.root is None
    assert manifest.binding["overlays"] == ["overlays/skills/demo"]
    root = package_root_from_agent_ref(f"file:{yaml_path}@dev")
    assert root == pkg.resolve()
    assert (root / "overlays" / "skills" / "demo" / "SKILL.md").is_file()


def test_cache_ref_resolves_installed(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    entry = store.install_from_path(pkg, agent_id="official/http-default")
    short = entry.digest[len("sha256:") :][:12]
    root = package_root_from_agent_ref(f"official/http-default@0.1.0+sha256:{short}")
    assert (root / "agent.yaml").is_file()
    assert root == store.resolve_package_root(entry)


def test_cache_ref_missing_fails_closed() -> None:
    with pytest.raises(ConfigError):
        package_root_from_agent_ref("official/missing@0.1.0+sha256:aaaaaaaaaaaa")


def test_cache_ref_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path), agent_id="official/http-default")
    with pytest.raises(ConfigError) as ei:
        package_root_from_agent_ref("official/http-default@0.1.0+sha256:ffffffffffff")
    assert ei.value.error_code == "invalid_package"
