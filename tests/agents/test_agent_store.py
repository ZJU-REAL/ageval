"""Agent cache install/list/uninstall + pinned ref resolve (design/14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.agents import store
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


def test_install_list_resolve_roundtrip(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    entry = store.install_from_path(pkg)
    assert entry.agent_id == "local/http-default"
    assert entry.version == "0.1.0"
    assert entry.digest.startswith("sha256:")

    rows = store.list_installed()
    assert [r.agent_id for r in rows] == ["local/http-default"]

    got, root = store.resolve_installed_ref("local/http-default", "0.1.0")
    assert got.digest == entry.digest
    assert (root / "agent.yaml").is_file()


def test_install_idempotent(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    a = store.install_from_path(pkg)
    b = store.install_from_path(pkg)
    assert a.digest == b.digest
    assert len(store.list_installed()) == 1


def test_install_reserved_short_id_fails_closed(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path, agent_id="pi")
    with pytest.raises(ConfigError, match="ships with ageval"):
        store.install_from_path(pkg)
    with pytest.raises(ConfigError, match="ships with ageval"):
        store.install_from_path(_make_pkg(tmp_path), agent_id="official/openai-http")


def test_hub_id_override(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    entry = store.install_from_path(pkg, agent_id="acme/http-default")
    assert entry.agent_id == "acme/http-default"
    _, root = store.resolve_installed_ref("acme/http-default", "0.1.0")
    assert root.is_dir()


def test_resolve_missing_fails_closed() -> None:
    with pytest.raises(ConfigError):
        store.resolve_installed_ref("local/nope", "1.0")


def test_resolve_version_mismatch_fails_closed(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path))
    with pytest.raises(ConfigError) as exc:
        store.resolve_installed_ref("local/http-default", "9.9")
    assert "9.9" in str(exc.value)


def test_install_writes_overlay_files(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path)
    skill = pkg / "overlays" / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# demo\n", encoding="utf-8")
    (pkg / "agent.yaml").write_text(
        "format: ageval.agent/1\nagent_id: http-default\nversion: '0.1.0'\n"
        "label: T\nbinding:\n  executor: openai-http\n  model: {id: none}\n"
        "  overlays: [overlays/skills/demo]\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    entry = store.install_from_path(pkg)
    root = store.resolve_package_root(entry)
    assert (root / "overlays" / "skills" / "demo" / "SKILL.md").is_file()
    assert not (dataset / "overlays").exists()


def test_uninstall(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path))
    assert store.uninstall("local/http-default") is True
    assert store.list_installed() == []
    assert store.uninstall("local/http-default") is False


def test_side_by_side_versions(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path, version="1.0.0"))
    store.install_from_path(_make_pkg(tmp_path, version="2.0.0"))
    rows = store.list_installed()
    assert sorted(r.version for r in rows) == ["1.0.0", "2.0.0"]
    v1, _ = store.resolve_installed_ref("local/http-default", "1.0.0")
    v2, _ = store.resolve_installed_ref("local/http-default", "2.0.0")
    assert v1.version == "1.0.0"
    assert v2.version == "2.0.0"
    newest = store.load_index().find("local/http-default")
    assert newest is not None
    assert newest.version == "2.0.0"


def test_uninstall_one_version_leaves_other(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path, version="1.0.0"))
    store.install_from_path(_make_pkg(tmp_path, version="2.0.0"))
    assert store.uninstall("local/http-default@1.0.0") is True
    versions = [r.version for r in store.list_installed()]
    assert versions == ["2.0.0"]
    store.resolve_installed_ref("local/http-default", "2.0.0")
    with pytest.raises(ConfigError):
        store.resolve_installed_ref("local/http-default", "1.0.0")


def test_uninstall_bare_id_removes_all_versions(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path, version="1.0.0"))
    store.install_from_path(_make_pkg(tmp_path, version="2.0.0"))
    assert store.uninstall("local/http-default") is True
    assert store.list_installed() == []


def test_reconcile_missing_version_row_from_disk(tmp_path: Path) -> None:
    store.install_from_path(_make_pkg(tmp_path, version="1.0.0"))
    store.install_from_path(_make_pkg(tmp_path, version="2.0.0"))
    newest = store.load_index(reconcile=False).find("local/http-default")
    assert newest is not None
    store.save_index(store.AgentIndex(agents=[newest]))
    got, root = store.resolve_installed_ref("local/http-default", "1.0.0")
    assert got.version == "1.0.0"
    assert (root / "agent.yaml").is_file()
    versions = sorted(r.version for r in store.list_installed())
    assert versions == ["1.0.0", "2.0.0"]
