"""Hub builtin contrib overlay: catalog union, not an upload."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.builtin_plugins import builtin_plugin_ids, catalog_rows
from services.registry.errors import RegistryAppError
from services.registry.package_service import PackageService
from services.registry.store import MemoryBlobStore, MetadataStore, TokenInfo

from ageval.registry.plugin_package import (
    PLUGIN_MEDIA_TYPE,
    build_plugin_archive,
    compute_plugin_digest,
)

REPO = Path(__file__).resolve().parents[2]
PLUGIN_FIXTURE = REPO / "tests" / "fixtures" / "plugins" / "sample-echo"
SEVEN = frozenset({"local", "docker", "e2b", "ssh", "daytona", "acp", "openai-http"})


def _service(tmp_path: Path) -> PackageService:
    meta = MetadataStore(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    return PackageService(meta, blobs, AccessPolicy(meta=meta), max_upload=64 * 1024 * 1024)


def _plugin_meta(tmp_path: Path) -> tuple[dict[str, object], Path]:
    archive, blob_digest, size = build_plugin_archive(PLUGIN_FIXTURE)
    path = tmp_path / "plugin.tar.gz"
    path.write_bytes(archive)
    return (
        {
            "dataset_id": "acme/sample-echo",
            "version": "0.1.0",
            "package_digest": compute_plugin_digest(PLUGIN_FIXTURE),
            "blob_digest": blob_digest,
            "media_type": PLUGIN_MEDIA_TYPE,
            "visibility": "public",
            "org_id": "acme",
            "package_kind": "plugin",
            "size": size,
        },
        path,
    )


def test_catalog_has_seven_contrib_ids() -> None:
    assert builtin_plugin_ids() == SEVEN
    assert [row["plugin_id"] for row in catalog_rows()] == [
        "local",
        "docker",
        "e2b",
        "ssh",
        "daytona",
        "acp",
        "openai-http",
    ]


def test_explore_unions_builtin_with_store(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.meta.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _plugin_meta(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    anon = TokenInfo(scopes=frozenset())
    listed = svc.list_packages(
        auth=anon,
        prefix=None,
        visibility="public",
        version=None,
        package_kind="plugin",
    )
    ids = [i["dataset_id"] for i in listed["items"]]
    assert ids[:7] == [
        "local",
        "docker",
        "e2b",
        "ssh",
        "daytona",
        "acp",
        "openai-http",
    ]
    assert "acme/sample-echo" in ids
    docker = next(i for i in listed["items"] if i["dataset_id"] == "docker")
    assert docker["builtin"] is True
    assert docker["official"] is False
    assert "org_id" not in docker
    assert "package_digest" not in docker
    assert "blob_digest" not in docker
    assert "version" not in docker
    preview = docker["plugin_preview"]
    assert preview["plugin_id"] == "docker"
    assert preview["slots"]["exclusive"] == ["environment"]
    assert preview["declared"][0]["id"] == "environment"
    e2b = next(i for i in listed["items"] if i["dataset_id"] == "e2b")
    assert e2b["host_requires"] == ["uv sync --extra e2b"]


def test_unfiltered_list_omits_builtin(tmp_path: Path) -> None:
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
        package_kind=None,
    )
    assert listed["items"] == []


def test_mine_orgs_favorited_omit_builtin(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.meta.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _plugin_meta(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    probes: list[tuple[str | None, str, bool, bool, bool]] = [
        (None, "plugin", True, False, False),
        (None, "plugin", False, True, False),
        (None, "plugin", False, False, True),
        ("private", "plugin", False, False, False),
        (None, "dataset", False, False, False),
        (None, "agent", False, False, False),
    ]
    for visibility, package_kind, mine, orgs, favorited in probes:
        listed = svc.list_packages(
            auth=alice,
            prefix=None,
            visibility=visibility,
            version=None,
            package_kind=package_kind,
            mine=mine,
            orgs=orgs,
            favorited=favorited,
        )
        assert not any(i.get("builtin") for i in listed["items"]), (
            visibility,
            package_kind,
            mine,
            orgs,
            favorited,
        )


def test_detail_has_no_blob(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    anon = TokenInfo(scopes=frozenset())
    versions = svc.list_versions(dataset_id="docker", auth=anon)
    assert len(versions["items"]) == 1
    row = versions["items"][0]
    assert row["builtin"] is True
    assert row["plugin_preview"]["plugin_id"] == "docker"
    meta = svc.serve_meta(dataset_id="acp", version=None, package_digest=None, auth=anon)
    assert meta["builtin"] is True
    assert meta["plugin_preview"]["slots"]["exclusive"] == ["executor"]
    mixed = svc.serve_meta(dataset_id="Docker", version=None, package_digest=None, auth=anon)
    assert mixed["dataset_id"] == "docker"
    assert mixed["builtin"] is True
    with pytest.raises(RegistryAppError) as digest_err:
        svc.serve_meta(
            dataset_id="docker",
            version=None,
            package_digest="sha256:" + "a" * 64,
            auth=anon,
        )
    assert digest_err.value.http_status == 404
    with pytest.raises(RegistryAppError) as ver_err:
        svc.serve_meta(dataset_id="docker", version="1.0.0", package_digest=None, auth=anon)
    assert ver_err.value.http_status == 404


def test_publish_reserved_plugin_id_fail_closed(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.meta.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _plugin_meta(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    for dataset_id in ("acme/docker", "acme/Docker"):
        meta["dataset_id"] = dataset_id
        with pytest.raises(RegistryAppError) as ei:
            svc.publish(meta=meta, archive=archive, auth=alice)
        assert ei.value.error == "plugin_id_reserved"
        assert ei.value.http_status == 400


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
