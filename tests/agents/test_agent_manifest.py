"""ageval.agent/1 manifest parse + fail-closed secret scan (design/14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ageval.agents.manifest import AGENT_FILENAME, load_agent_manifest, parse_agent_document
from ageval.config.errors import ConfigError

GOOD_DOC = {
    "format": "ageval.agent/1",
    "agent_id": "http-default",
    "version": "0.1.0",
    "label": "Mock Default",
    "tags": ["ci"],
    "binding": {
        "executor": "openai-http",
        "model": {"id": "none"},
    },
}


def _write_pkg(root: Path, doc_text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / AGENT_FILENAME).write_text(doc_text, encoding="utf-8")
    return root


def test_parse_good_document() -> None:
    m = parse_agent_document(dict(GOOD_DOC))
    assert m.agent_id == "http-default"
    assert m.version == "0.1.0"
    assert m.binding["executor"] == "openai-http"
    # label sinks into binding.label when binding omits it
    assert m.binding["label"] == "Mock Default"
    assert m.tags == ("ci",)


def test_unknown_top_key_fails() -> None:
    doc = dict(GOOD_DOC)
    doc["skills"] = ["x"]
    with pytest.raises(ConfigError):
        parse_agent_document(doc)


def test_bad_format_fails() -> None:
    doc = dict(GOOD_DOC)
    doc["format"] = "ageval.agent/2"
    with pytest.raises(ConfigError):
        parse_agent_document(doc)


def test_reserved_agent_ref_rejected() -> None:
    doc = dict(GOOD_DOC)
    doc["binding"] = {"executor": "openai-http", "model": {"id": "none"}, "agent_ref": "x@1"}
    with pytest.raises(ConfigError) as exc:
        parse_agent_document(doc)
    assert "agent_ref" in str(exc.value)


def test_unknown_binding_key_rejected() -> None:
    doc = dict(GOOD_DOC)
    doc["binding"] = {"executor": "openai-http", "model": {"id": "none"}, "token": "sk-nope"}
    with pytest.raises(ConfigError):
        parse_agent_document(doc)


def test_load_from_dir_and_bare_yaml(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "agent-pkg",
        "format: ageval.agent/1\nagent_id: a1\nversion: '1.0'\n"
        "binding: {executor: openai-http, model: {id: none}}\n",
    )
    m = load_agent_manifest(pkg)
    assert m.root == pkg
    m2 = load_agent_manifest(pkg / AGENT_FILENAME)
    assert m2.root is None
    assert m2.agent_id == "a1"


def test_secret_in_package_fails_closed(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "leaky",
        "format: ageval.agent/1\nagent_id: leaky\nversion: '1.0'\n"
        "binding: {executor: openai-http, model: {id: none}}\n",
    )
    (pkg / "notes.txt").write_text("api_key = sk-abc123def456ghi789jkl000\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_agent_manifest(pkg)


def test_listed_overlay_must_exist_in_package(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "missing-overlay",
        "format: ageval.agent/1\nagent_id: missing\nversion: '1.0'\n"
        "binding:\n  executor: openai-http\n  model: {id: none}\n"
        "  overlays: [overlays/skills/demo]\n",
    )
    with pytest.raises(ConfigError) as ei:
        load_agent_manifest(pkg)
    assert ei.value.error_code == "missing_reference"


def test_listed_overlay_files_are_accepted(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "with-overlay",
        "format: ageval.agent/1\nagent_id: withov\nversion: '1.0'\n"
        "binding:\n  executor: openai-http\n  model: {id: none}\n"
        "  overlays: [overlays/skills/demo]\n",
    )
    skill = pkg / "overlays" / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# demo\n", encoding="utf-8")
    m = load_agent_manifest(pkg)
    assert m.binding["overlays"] == ["overlays/skills/demo"]
    m_yaml = load_agent_manifest(pkg / AGENT_FILENAME)
    assert m_yaml.root is None
    assert m_yaml.binding["overlays"] == ["overlays/skills/demo"]


def test_listed_overlay_missing_from_bare_yaml_fails_closed(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "missing-overlay-yaml",
        "format: ageval.agent/1\nagent_id: missing\nversion: '1.0'\n"
        "binding:\n  executor: openai-http\n  model: {id: none}\n"
        "  overlays: [overlays/skills/demo]\n",
    )
    with pytest.raises(ConfigError) as ei:
        load_agent_manifest(pkg / AGENT_FILENAME)
    assert ei.value.error_code == "missing_reference"


def test_secret_in_overlay_file_fails_closed(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "secret-overlay",
        "format: ageval.agent/1\nagent_id: secretov\nversion: '1.0'\n"
        "binding:\n  executor: openai-http\n  model: {id: none}\n"
        "  overlays: [overlays/secret.md]\n",
    )
    path = pkg / "overlays" / "secret.md"
    path.parent.mkdir(parents=True)
    path.write_text("-----BEGIN PRIVATE KEY-----\nabc\n", encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_agent_manifest(pkg)
    assert ei.value.error_code == "invalid_package"


def test_locator_name_is_clean(tmp_path: Path) -> None:
    pkg = _write_pkg(
        tmp_path / "locator",
        "format: ageval.agent/1\nagent_id: locator\nversion: '1.0'\n"
        "binding: {executor: openai-http, model: {id: none}, api_key: '${OPENAI_API_KEY}'}\n",
    )
    m = load_agent_manifest(pkg)
    assert m.binding["api_key"] == "${OPENAI_API_KEY}"
