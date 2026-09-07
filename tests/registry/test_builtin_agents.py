"""Hub builtin agent overlay: catalog union, not an upload."""

from __future__ import annotations

import ast
import json
from io import BytesIO
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.app import build_default_state
from services.registry.builtin_agents import builtin_harness_ids
from services.registry.errors import RegistryAppError
from services.registry.http_api import RegistryHttpApi
from services.registry.package_service import PackageService
from services.registry.store import MemoryBlobStore, TokenInfo
from services.registry.store_schema import (
    open_sqlite_stores,
)

from ageval.registry.agent_package import (
    AGENT_MEDIA_TYPE,
    build_agent_archive,
    compute_agent_digest,
)

REPO = Path(__file__).resolve().parents[2]
AGENT_FIXTURE = REPO / "examples" / "agents" / "pi-default"
SEVEN = frozenset(
    {"pi", "opencode", "codex", "claude-code", "grok-build", "openai-http", "anthropic-http"}
)


def _service(tmp_path: Path) -> PackageService:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    return PackageService(
        meta.packages,
        meta.orgs,
        blobs,
        AccessPolicy(orgs=meta.orgs, packages=meta.packages, results=meta.results),
        max_upload=64 * 1024 * 1024,
    )


def _agent_meta(tmp_path: Path) -> tuple[dict[str, object], Path]:
    archive, blob_digest, size = build_agent_archive(AGENT_FIXTURE)
    path = tmp_path / "agent.tar.gz"
    path.write_bytes(archive)
    return (
        {
            "dataset_id": "acme/pi-default",
            "version": "0.1.0",
            "package_digest": compute_agent_digest(AGENT_FIXTURE),
            "blob_digest": blob_digest,
            "media_type": AGENT_MEDIA_TYPE,
            "visibility": "public",
            "org_id": "acme",
            "package_kind": "agent",
            "size": size,
        },
        path,
    )


def test_catalog_has_seven_harness_ids() -> None:
    assert builtin_harness_ids() == SEVEN


def test_explore_unions_builtin_with_store(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _agent_meta(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    anon = TokenInfo(scopes=frozenset())
    listed = svc.list_packages(
        auth=anon,
        prefix=None,
        visibility="public",
        version=None,
        package_kind="agent",
    )
    ids = [i["dataset_id"] for i in listed["items"]]
    assert ids[:7] == [
        "pi",
        "opencode",
        "codex",
        "claude-code",
        "grok-build",
        "openai-http",
        "anthropic-http",
    ]
    assert "acme/pi-default" in ids
    opencode = next(i for i in listed["items"] if i["dataset_id"] == "opencode")
    assert opencode["builtin"] is True
    assert opencode["icon_key"] == "opencode"
    assert opencode["display_name"] == "OpenCode"
    assert opencode["official"] is False
    assert "org_id" not in opencode
    assert "package_digest" not in opencode
    assert "blob_digest" not in opencode
    assert "version" not in opencode
    preview = opencode["agent_preview"]
    assert preview["agent_id"] == "opencode"
    assert preview["format"] == "ageval.agent/1"
    assert preview["binding"]["executor"] == "acp"
    assert "agent.yaml" in preview["files"]
    assert "overlays/opencode.litellm.json" in preview["files"]
    pi = next(i for i in listed["items"] if i["dataset_id"] == "pi")
    assert "model" not in pi["agent_preview"]["binding"]
    assert not any(str(p).startswith("overlays/") for p in pi["agent_preview"]["files"])


def test_unfiltered_list_omits_builtin_agents(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    anon = TokenInfo(scopes=frozenset())
    listed = svc.list_packages(
        auth=anon,
        prefix=None,
        visibility=None,
        version=None,
        package_kind=None,
    )
    assert listed["items"] == []
    listed = svc.list_packages(
        auth=anon,
        prefix=None,
        visibility="public",
        version=None,
        package_kind="plugin",
    )
    assert not any(i.get("package_kind") == "agent" and i.get("builtin") for i in listed["items"])


def test_mine_orgs_favorited_omit_builtin_agents(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _agent_meta(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    probes: list[tuple[str | None, bool, bool, bool]] = [
        (None, True, False, False),
        (None, False, True, False),
        (None, False, False, True),
        ("private", False, False, False),
    ]
    for visibility, mine, orgs, favorited in probes:
        listed = svc.list_packages(
            auth=alice,
            prefix=None,
            visibility=visibility,
            version=None,
            package_kind="agent",
            mine=mine,
            orgs=orgs,
            favorited=favorited,
        )
        assert not any(i.get("builtin") for i in listed["items"]), (
            visibility,
            mine,
            orgs,
            favorited,
        )


def test_detail_and_files_have_no_blob(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    anon = TokenInfo(scopes=frozenset())
    versions = svc.list_versions(dataset_id="pi", auth=anon)
    assert len(versions["items"]) == 1
    row = versions["items"][0]
    assert row["builtin"] is True
    assert row["agent_preview"]["agent_id"] == "pi"
    meta = svc.serve_meta(dataset_id="opencode", version=None, package_digest=None, auth=anon)
    assert meta["builtin"] is True
    assert "overlays/opencode.litellm.json" in meta["agent_preview"]["files"]
    mixed = svc.serve_meta(dataset_id="Pi", version=None, package_digest=None, auth=anon)
    assert mixed["dataset_id"] == "pi"
    assert mixed["builtin"] is True
    with pytest.raises(RegistryAppError) as digest_err:
        svc.serve_meta(
            dataset_id="pi",
            version=None,
            package_digest="sha256:" + "a" * 64,
            auth=anon,
        )
    assert digest_err.value.http_status == 404
    with pytest.raises(RegistryAppError) as ver_err:
        svc.serve_meta(dataset_id="pi", version="1.0.0", package_digest=None, auth=anon)
    assert ver_err.value.http_status == 404
    listed = svc.list_files(dataset_id="opencode", auth=anon)
    paths = {item["path"] for item in listed["items"]}
    assert "agent.yaml" in paths
    assert "overlays/opencode.litellm.json" in paths
    payload = svc.read_file(dataset_id="opencode", file_path="agent.yaml", auth=anon)
    assert payload["encoding"] == "utf-8"
    assert "agent_id: opencode" in payload["content"]
    overlay = svc.read_file(
        dataset_id="OpenCode",
        file_path="overlays/opencode.litellm.json",
        auth=anon,
    )
    assert "litellm_base_url" in overlay["content"]
    pi_files = {item["path"] for item in svc.list_files(dataset_id="pi", auth=anon)["items"]}
    assert "agent.yaml" in pi_files
    assert not any(p.startswith("overlays/") for p in pi_files)


def test_openai_http_kind_collision(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    anon = TokenInfo(scopes=frozenset())
    plugin = svc.list_versions(dataset_id="openai-http", auth=anon)
    assert plugin["items"][0]["package_kind"] == "plugin"
    assert plugin["items"][0]["builtin"] is True
    agent = svc.list_versions(dataset_id="openai-http", auth=anon, package_kind="agent")
    assert agent["items"][0]["package_kind"] == "agent"
    assert agent["items"][0]["agent_preview"]["agent_id"] == "openai-http"
    plugin_files = svc.list_files(dataset_id="openai-http", auth=anon)
    assert any(item["path"] == "plugin.yaml" for item in plugin_files["items"])
    agent_files = svc.list_files(dataset_id="openai-http", auth=anon, package_kind="agent")
    assert any(item["path"] == "agent.yaml" for item in agent_files["items"])
    plugin_body = svc.read_file(dataset_id="openai-http", file_path="plugin.yaml", auth=anon)
    assert "plugin_id: openai-http" in plugin_body["content"]
    agent_body = svc.read_file(
        dataset_id="openai-http",
        file_path="agent.yaml",
        auth=anon,
        package_kind="agent",
    )
    assert "agent_id: openai-http" in agent_body["content"]


def test_publish_reserved_agent_id_fail_closed(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _agent_meta(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    for dataset_id in ("acme/pi", "acme/OpenAI-HTTP", "pi"):
        meta["dataset_id"] = dataset_id
        with pytest.raises(RegistryAppError) as ei:
            svc.publish(meta=meta, archive=archive, auth=alice)
        assert ei.value.error == "agent_id_reserved"
        assert ei.value.http_status == 400


def test_http_explore_and_kind_query(tmp_path: Path) -> None:
    state, token = build_default_state(tmp_path / "http", bootstrap_token="tok", memory_blob=True)
    api = RegistryHttpApi(state)
    headers = {"Authorization": f"Bearer {token}"}
    listed = api.dispatch(
        method="GET",
        path="/v1/packages?package_kind=agent",
        headers=headers,
        body=BytesIO(),
        content_length=0,
    )
    assert listed.status == 200, listed.body.decode()
    payload = json.loads(listed.body.decode())
    ids = [i["dataset_id"] for i in payload["items"]]
    assert ids[:7] == [
        "pi",
        "opencode",
        "codex",
        "claude-code",
        "grok-build",
        "openai-http",
        "anthropic-http",
    ]
    plugin = api.dispatch(
        method="GET",
        path="/v1/packages/openai-http",
        headers=headers,
        body=BytesIO(),
        content_length=0,
    )
    assert plugin.status == 200
    plugin_body = json.loads(plugin.body.decode())
    assert plugin_body["items"][0]["package_kind"] == "plugin"
    agent = api.dispatch(
        method="GET",
        path="/v1/packages/openai-http?package_kind=agent",
        headers=headers,
        body=BytesIO(),
        content_length=0,
    )
    assert agent.status == 200
    agent_body = json.loads(agent.body.decode())
    assert agent_body["items"][0]["package_kind"] == "agent"
    files = api.dispatch(
        method="GET",
        path="/v1/packages/openai-http/files?package_kind=agent",
        headers=headers,
        body=BytesIO(),
        content_length=0,
    )
    assert files.status == 200
    file_body = json.loads(files.body.decode())
    assert any(item["path"] == "agent.yaml" for item in file_body["items"])


def test_registry_sources_do_not_import_contrib() -> None:
    root = REPO / "services" / "registry"
    banned = "ageval.plugins.contrib"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert banned not in alias.name, path
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert banned not in node.module, path
