"""plugin_id identity: local short ids vs Hub org/name."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.config.errors import ConfigError
from ageval.plugins.manifest import (
    PluginManifestError,
    hub_plugin_package_id,
    normalize_plugin_id,
    parse_manifest_mapping,
    split_plugin_id,
)


def test_normalize_short_and_namespaced() -> None:
    assert normalize_plugin_id("nooa") == "nooa"
    assert normalize_plugin_id("sample-echo") == "sample-echo"
    assert normalize_plugin_id("acme/nooa") == "acme/nooa"
    assert normalize_plugin_id("Official/acp") == "Official/acp"
    assert split_plugin_id("acme/nooa") == ("acme", "nooa")
    assert split_plugin_id("dsh") == (None, "dsh")


@pytest.mark.parametrize(
    "raw",
    ["org.name", "acme//nooa", "acme/nooa/extra", "-bad", "acme/", "/nooa", ""],
)
def test_normalize_rejects_invalid(raw: str) -> None:
    with pytest.raises(PluginManifestError) as ei:
        normalize_plugin_id(raw)
    assert ei.value.kind in {"plugin_id_invalid", "plugin_manifest_invalid"}


def test_parse_manifest_keeps_short_id() -> None:
    manifest = parse_manifest_mapping(
        {
            "format": "ageval.plugin/1",
            "plugin_id": "dsh",
            "version": "0.1.0",
            "slots": {"exclusive": [{"id": "executor", "entry": "pkg:fn"}]},
        }
    )
    assert manifest.plugin_id == "dsh"
    assert manifest.description is None


def test_parse_manifest_description() -> None:
    manifest = parse_manifest_mapping(
        {
            "format": "ageval.plugin/1",
            "plugin_id": "dsh",
            "version": "0.1.0",
            "description": "  Run DeepSeek Harness in the box.  ",
            "slots": {"exclusive": [{"id": "executor", "entry": "pkg:fn"}]},
        }
    )
    assert manifest.description == "Run DeepSeek Harness in the box."


def test_parse_manifest_description_keeps_markdown_link() -> None:
    url = "https://github.com/NVIDIA-NeMo/labs-OO-Agents"
    manifest = parse_manifest_mapping(
        {
            "format": "ageval.plugin/1",
            "plugin_id": "nooa",
            "version": "0.1.0",
            "description": f"Run [NVIDIA OO Agents]({url}) in the box.",
        }
    )
    assert manifest.description == f"Run [NVIDIA OO Agents]({url}) in the box."


@pytest.mark.parametrize("raw", ["", "   ", 12, []])
def test_parse_manifest_description_fail_closed(raw: object) -> None:
    with pytest.raises(PluginManifestError) as ei:
        parse_manifest_mapping(
            {
                "format": "ageval.plugin/1",
                "plugin_id": "dsh",
                "version": "0.1.0",
                "description": raw,
            }
        )
    assert ei.value.kind == "plugin_manifest_invalid"
    assert "description" in str(ei.value)


def test_repo_plugins_declare_description() -> None:
    from ageval.plugins.manifest import load_manifest

    root = Path(__file__).resolve().parents[2] / "plugins"
    names = ("agent-skills", "dsh", "home-files", "miniswe", "nooa")
    for name in names:
        man = load_manifest(root / name)
        assert man.description, f"{name} missing description"


def test_hub_publish_concatenates_short_id() -> None:
    assert hub_plugin_package_id("nooa", org="Official") == "Official/nooa"
    assert hub_plugin_package_id("sample-echo", org="test") == "test/sample-echo"


def test_hub_publish_namespaced_must_match_org() -> None:
    assert hub_plugin_package_id("test/sample-echo", org="test") == "test/sample-echo"
    with pytest.raises(PluginManifestError) as mismatch:
        hub_plugin_package_id("other/sample-echo", org="test")
    assert mismatch.value.kind == "plugin_org_mismatch"


def test_publish_command_rejects_org_mismatch(tmp_path: Path) -> None:
    from ageval.application.plugin_ops.plugin_publish import PluginPublishCommand

    root = tmp_path / "plug"
    root.mkdir()
    (root / "plugin.yaml").write_text(
        "format: ageval.plugin/1\nplugin_id: acme/echo\nversion: 0.0.1\n",
        encoding="utf-8",
    )
    cmd = PluginPublishCommand(client_factory=lambda **_k: None)
    with pytest.raises(ConfigError) as ei:
        cmd.publish_plugin(root, org="other")
    assert ei.value.error_code == "plugin_org_mismatch"


def test_publish_command_concatenates_short_id(tmp_path: Path) -> None:
    from ageval.application.plugin_ops.plugin_publish import PluginPublishCommand

    class _Client:
        def publish(self, **kwargs):  # type: ignore[no-untyped-def]
            return type(
                "Info",
                (),
                {
                    "dataset_id": kwargs["dataset_id"],
                    "version": kwargs["version"],
                    "visibility": kwargs["visibility"],
                    "package_digest": kwargs["package_digest"],
                    "blob_digest": kwargs["blob_digest"],
                    "size": kwargs["size"],
                    "media_type": kwargs["media_type"],
                    "org_id": kwargs["org_id"],
                },
            )()

    root = tmp_path / "plug"
    root.mkdir()
    (root / "plugin.yaml").write_text(
        "format: ageval.plugin/1\nplugin_id: sample-echo\nversion: 0.0.1\n",
        encoding="utf-8",
    )
    cmd = PluginPublishCommand(client_factory=lambda **_k: _Client())
    summary = cmd.publish_plugin(root, org="Official")
    assert summary["package_id"] == "Official/sample-echo"
    assert summary["plugin_id"] == "sample-echo"
    assert summary["ref"] == "Official/sample-echo@0.0.1"


def test_path_install_keeps_short_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins.store import install_from_path, list_installed, uninstall

    src = tmp_path / "src"
    src.mkdir()
    (src / "plugin.yaml").write_text(
        "format: ageval.plugin/1\nplugin_id: nooa\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    (src / "readme.txt").write_text("hi\n", encoding="utf-8")
    entry = install_from_path(src)
    assert entry.plugin_id == "nooa"
    assert entry.digest.startswith("sha256:")
    assert (home / "plugins" / "nooa" / "0.1.0" / "plugin.yaml").is_file()
    assert list_installed()[0].plugin_id == "nooa"
    assert uninstall("nooa") is True
    assert list_installed() == []


def test_hub_install_records_namespaced_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins.store import install_from_path, list_installed

    src = tmp_path / "src"
    src.mkdir()
    (src / "plugin.yaml").write_text(
        "format: ageval.plugin/1\nplugin_id: nooa\nversion: 0.1.0\n"
        "slots:\n  exclusive:\n    - id: executor\n      entry: missing:fn\n",
        encoding="utf-8",
    )
    entry = install_from_path(src, plugin_id="Official/nooa")
    assert entry.plugin_id == "Official/nooa"
    assert entry.version == "0.1.0"
    assert entry.digest.startswith("sha256:")
    assert (home / "plugins" / "Official" / "nooa" / "0.1.0" / "plugin.yaml").is_file()
    assert list_installed()[0].plugin_id == "Official/nooa"


def test_hub_install_registers_index_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    from ageval.plugins import bootstrap as boot
    from ageval.plugins.bootstrap import bootstrap_registry
    from ageval.plugins.registry import ExtensionRegistry, reset_global_registry
    from ageval.plugins.slots import EXECUTOR
    from ageval.plugins.store import install_from_path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "plugins" / "sample-echo"
    install_from_path(fixture, plugin_id="Official/sample-echo")
    boot._BOOTSTRAPPED = False  # type: ignore[attr-defined]
    reset_global_registry()
    reg = ExtensionRegistry()
    bootstrap_registry(reg)
    assert "Official/sample-echo" in reg.plugins_for_slot(EXECUTOR)
    assert "sample-echo" not in reg.plugins_for_slot(EXECUTOR)


def test_release_dict_marks_official_from_allowlist() -> None:
    from services.registry.store import ReleaseRow, release_to_dict

    from ageval.registry.plugin_package import PLUGIN_MEDIA_TYPE

    official = release_to_dict(
        ReleaseRow(
            dataset_id="Official/nooa",
            version="0.1.0",
            visibility="public",
            package_digest="sha256:a",
            blob_digest="sha256:b",
            size=1,
            media_type=PLUGIN_MEDIA_TYPE,
            created_at=0.0,
            org_id="Official",
        )
    )
    other = release_to_dict(
        ReleaseRow(
            dataset_id="acme/nooa",
            version="0.1.0",
            visibility="public",
            package_digest="sha256:a",
            blob_digest="sha256:b",
            size=1,
            media_type=PLUGIN_MEDIA_TYPE,
            created_at=0.0,
            org_id="acme",
        )
    )
    assert official["official"] is True
    assert other["official"] is False


def test_official_org_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.registry.orgs.official import is_official_upload_org, official_orgs

    monkeypatch.delenv("AGEVAL_OFFICIAL_ORGS", raising=False)
    assert "official" in official_orgs()
    assert is_official_upload_org("official") is True
    assert is_official_upload_org("Official") is True
    assert is_official_upload_org("acme") is False
    monkeypatch.setenv("AGEVAL_OFFICIAL_ORGS", "Acme, Labs")
    assert official_orgs() == frozenset({"Acme", "Labs"})
    assert is_official_upload_org("Acme") is True
    assert is_official_upload_org("Official") is False
