"""PackageService.publish is a real domain module (no HTTP objects)."""

from __future__ import annotations

from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.blob_io import read_blob
from services.registry.errors import RegistryAppError
from services.registry.package_service import PackageService
from services.registry.store import (
    MemoryBlobStore,
    TokenInfo,
)
from services.registry.store_schema import (
    open_sqlite_stores,
)

from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.digest import compute_package_digest
from ageval.registry.plugin_package import (
    PLUGIN_MEDIA_TYPE,
    build_plugin_archive,
    compute_plugin_digest,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
PLUGIN_FIXTURE = REPO / "tests" / "fixtures" / "plugins" / "sample-echo"


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


def _meta_archive(tmp_path: Path) -> tuple[dict[str, object], Path, bytes]:
    archive, blob_digest, size = build_archive(FIXTURE)
    path = tmp_path / "pkg.tar.gz"
    path.write_bytes(archive)
    return (
        {
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "package_digest": compute_package_digest(FIXTURE),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "private",
            "org_id": "acme",
            "size": size,
        },
        path,
        archive,
    )


def test_publish_missing_org(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    with pytest.raises(RegistryAppError) as ei:
        svc.publish(meta=meta, archive=archive, auth=auth)
    assert ei.value.error == "org_not_found"
    assert ei.value.http_status == 400


def test_publish_requires_membership(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="owner", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    with pytest.raises(RegistryAppError) as ei:
        svc.publish(meta=meta, archive=archive, auth=auth)
    assert ei.value.error == "forbidden"
    assert ei.value.http_status == 403


def test_publish_happy_path(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.publish(meta=meta, archive=archive, auth=auth)
    assert payload["dataset_id"] == "test/publish-min"
    assert payload["org_id"] == "acme"
    assert payload.get("uploaded_by") == "alice"
    row = svc.get("test/publish-min", "0.1.0")
    assert row is not None
    assert read_blob(svc.blobs, row.blob_digest, prefix="packages") == _raw
    mine = svc.list_packages(
        auth=auth,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="dataset",
        mine=True,
    )
    assert [i["dataset_id"] for i in mine["items"]] == ["test/publish-min"]
    other = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="bob")
    empty = svc.list_packages(
        auth=other,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="dataset",
        mine=True,
    )
    assert empty["items"] == []
    assert payload["download_count"] == 0


def test_list_packages_attaches_dataset_description(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=auth)
    listed = svc.list_packages(
        auth=auth,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="dataset",
    )
    row = next(i for i in listed["items"] if i["dataset_id"] == "test/publish-min")
    assert row["description"] == "Minimal Dataset for registry publish e2e"


def test_patch_description_overrides_and_clears(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=auth)

    patched = svc.patch_marketplace(
        dataset_id="test/publish-min",
        auth=auth,
        description="  Owner-set copy  ",
        has_description=True,
    )
    assert patched["description"] == "Owner-set copy"

    listed = svc.list_packages(
        auth=auth,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="dataset",
    )
    row = next(i for i in listed["items"] if i["dataset_id"] == "test/publish-min")
    assert row["description"] == "Owner-set copy"

    cleared = svc.patch_marketplace(
        dataset_id="test/publish-min",
        auth=auth,
        description="",
        has_description=True,
    )
    assert cleared["description"] == "Minimal Dataset for registry publish e2e"

    with pytest.raises(RegistryAppError) as ei:
        svc.patch_marketplace(
            dataset_id="test/publish-min",
            auth=auth,
            description="x" * 501,
            has_description=True,
        )
    assert ei.value.error == "invalid_request"


def test_content_increments_download_count_files_do_not(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.publish(meta=meta, archive=archive, auth=auth)
    digest = str(payload["package_digest"])
    svc.list_files(dataset_id="test/publish-min", auth=auth, package_digest=digest)
    svc.read_file(
        dataset_id="test/publish-min",
        file_path="ageval.yaml",
        auth=auth,
        package_digest=digest,
    )
    listed = svc.list_packages(
        auth=auth,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="dataset",
    )
    row = next(i for i in listed["items"] if i["dataset_id"] == "test/publish-min")
    assert row["download_count"] == 0
    assert row["task_count"] == 1
    fh, size, release = svc.serve_content(
        dataset_id="test/publish-min", package_digest=digest, auth=auth
    )
    assert size > 0
    assert release.dataset_id == "test/publish-min"
    fh.close()
    after = svc.serve_meta(
        dataset_id="test/publish-min",
        version=None,
        package_digest=digest,
        auth=auth,
    )
    assert after["download_count"] == 1
    svc.list_files(dataset_id="test/publish-min", auth=auth, package_digest=digest)
    still = svc.serve_meta(
        dataset_id="test/publish-min",
        version=None,
        package_digest=digest,
        auth=auth,
    )
    assert still["download_count"] == 1


def test_draft_overwrite_and_entitled_list(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    first = svc.publish(meta=meta, archive=archive, auth=alice)
    assert first["version"] == "draft"
    assert first["is_draft"] is True
    assert first["replaced"] is False
    assert svc.packages.dataset_acl("test/publish-min", "alice") is not None

    second = svc.publish(meta=meta, archive=archive, auth=alice)
    assert second["replaced"] is True

    versions = svc.list_versions(dataset_id="test/publish-min", auth=alice)
    assert any(i.get("version") == "draft" for i in versions["items"])

    stranger = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="bob")
    hidden = svc.list_versions(dataset_id="test/publish-min", auth=stranger)
    assert hidden["items"] == []


def test_draft_hidden_from_non_entitled_get(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    stranger = TokenInfo(scopes=frozenset(), user_id="bob")
    with pytest.raises(RegistryAppError) as ei:
        svc.serve_meta(
            dataset_id="test/publish-min",
            version="draft",
            package_digest=None,
            auth=stranger,
        )
    assert ei.value.http_status == 404


def test_release_draft_creates_durable_version(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    released = svc.release_draft(dataset_id="test/publish-min", auth=alice)
    assert released["version"] == "0.1.0"
    assert released.get("from_draft") is True
    assert released.get("is_draft") is not True
    row = svc.get("test/publish-min", "0.1.0")
    assert row is not None


def test_collaborator_cannot_release(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.add_member("acme", "bob", role="member")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    svc.packages.upsert_dataset_acl("test/publish-min", "bob", role="collaborator")
    bob = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="bob")
    with pytest.raises(RegistryAppError) as ei:
        svc.release_draft(dataset_id="test/publish-min", auth=bob)
    assert ei.value.http_status == 404


def test_reserved_version_draft_rejected_on_release_publish(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["version"] = "draft"
    # Without slot, version=draft still takes the draft path (reserved).
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.publish(meta=meta, archive=archive, auth=alice)
    assert payload["version"] == "draft"
    assert payload["is_draft"] is True


def test_anon_sees_public_release_not_draft(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    svc.release_draft(dataset_id="test/publish-min", auth=alice, visibility="public")
    svc.publish(meta=meta, archive=archive, auth=alice)

    anon = TokenInfo(scopes=frozenset())
    versions = svc.list_versions(dataset_id="test/publish-min", auth=anon)
    assert [i["version"] for i in versions["items"]] == ["0.1.0"]
    assert all(not i.get("is_draft") for i in versions["items"])
    listed = svc.list_packages(
        auth=anon, prefix=None, visibility=None, version=None, package_kind="dataset"
    )
    assert [i["version"] for i in listed["items"]] == ["0.1.0"]
    with pytest.raises(RegistryAppError) as ei:
        svc.serve_meta(
            dataset_id="test/publish-min",
            version="draft",
            package_digest=None,
            auth=anon,
        )
    assert ei.value.http_status == 404
    release = svc.serve_meta(
        dataset_id="test/publish-min",
        version="0.1.0",
        package_digest=None,
        auth=anon,
    )
    assert release["version"] == "0.1.0"


def test_org_member_can_read_draft(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.add_member("acme", "carol", role="member")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    carol = TokenInfo(scopes=frozenset(), user_id="carol")
    versions = svc.list_versions(dataset_id="test/publish-min", auth=carol)
    assert any(i.get("version") == "draft" for i in versions["items"])
    draft = svc.serve_meta(
        dataset_id="test/publish-min",
        version="draft",
        package_digest=None,
        auth=carol,
    )
    assert draft["is_draft"] is True


def test_draft_first_upload_requires_org_membership(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["slot"] = "draft"
    bob = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="bob")
    with pytest.raises(RegistryAppError) as ei:
        svc.publish(meta=meta, archive=archive, auth=bob)
    assert ei.value.error == "forbidden"
    assert ei.value.http_status == 403


def _plugin_meta_archive(tmp_path: Path) -> tuple[dict[str, object], Path]:
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


def test_favorite_plugin_and_list_favorited(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _plugin_meta_archive(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    bob = TokenInfo(scopes=frozenset({"results:read"}), user_id="bob")
    published = svc.publish(meta=meta, archive=archive, auth=alice)
    assert published["favorite_count"] == 0
    assert published["favorited"] is False

    added = svc.set_favorite(dataset_id="acme/sample-echo", auth=bob, favorited=True)
    assert added["favorited"] is True
    assert added["favorite_count"] == 1
    again = svc.set_favorite(dataset_id="acme/sample-echo", auth=bob, favorited=True)
    assert again["favorite_count"] == 1

    listed = svc.list_packages(
        auth=bob,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
        favorited=True,
    )
    assert [i["dataset_id"] for i in listed["items"]] == ["acme/sample-echo"]
    row = listed["items"][0]
    assert row["favorited"] is True
    assert row["favorite_count"] == 1

    alice_list = svc.list_packages(
        auth=alice,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
    )
    alice_row = next(i for i in alice_list["items"] if i["dataset_id"] == "acme/sample-echo")
    assert alice_row["favorited"] is False
    assert alice_row["favorite_count"] == 1

    anon = TokenInfo(scopes=frozenset({"results:read"}), user_id=None)
    anon_fav = svc.list_packages(
        auth=anon,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
        favorited=True,
    )
    assert anon_fav["items"] == []

    removed = svc.set_favorite(dataset_id="acme/sample-echo", auth=bob, favorited=False)
    assert removed["favorited"] is False
    assert removed["favorite_count"] == 0
    empty = svc.list_packages(
        auth=bob,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
        favorited=True,
    )
    assert empty["items"] == []


def test_list_packages_orgs_filter(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    svc.orgs.create_org(name="other", owner_user_id="carol", display_name="Other")
    meta, archive = _plugin_meta_archive(tmp_path)
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    bob = TokenInfo(scopes=frozenset({"results:read"}), user_id="bob")
    mine = svc.list_packages(
        auth=alice,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
        orgs=True,
    )
    assert [i["dataset_id"] for i in mine["items"]] == ["acme/sample-echo"]
    outsider = svc.list_packages(
        auth=bob,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
        orgs=True,
    )
    assert outsider["items"] == []
    anon = TokenInfo(scopes=frozenset({"results:read"}), user_id=None)
    empty = svc.list_packages(
        auth=anon,
        prefix=None,
        visibility=None,
        version=None,
        package_kind="plugin",
        orgs=True,
    )
    assert empty["items"] == []


def test_favorite_rejects_dataset_and_anonymous(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    meta["visibility"] = "public"
    alice = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=alice)
    bob = TokenInfo(scopes=frozenset({"results:read"}), user_id="bob")
    with pytest.raises(RegistryAppError) as ei:
        svc.set_favorite(dataset_id="test/publish-min", auth=bob, favorited=True)
    assert ei.value.error == "invalid_request"
    assert ei.value.http_status == 400
    anon = TokenInfo(scopes=frozenset({"results:read"}), user_id=None)
    with pytest.raises(RegistryAppError) as anon_err:
        svc.set_favorite(dataset_id="test/publish-min", auth=anon, favorited=True)
    assert anon_err.value.http_status == 401


def test_list_tasks_pages_and_flags(tmp_path: Path) -> None:
    from services.registry.package_files import FileEntry, PackageFileIndex

    index = PackageFileIndex(
        package_digest="sha256:abc",
        entries=[
            FileEntry(path="tasks/a/task.yaml", type="file", size=1),
            FileEntry(path="tasks/a/README.md", type="file", size=1),
            FileEntry(path="tasks/b/task.yaml", type="file", size=1),
            FileEntry(path="shared/note.txt", type="file", size=1),
        ],
        _by_path={},
    )
    items, has_shared = index.list_tasks()
    assert has_shared is True
    assert items == [
        {"task_id": "a", "has_readme": True},
        {"task_id": "b", "has_readme": False},
    ]

    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.publish(meta=meta, archive=archive, auth=auth)
    digest = str(payload["package_digest"])
    listed = svc.list_tasks(
        dataset_id="test/publish-min",
        auth=auth,
        package_digest=digest,
        limit=50,
        offset=0,
    )
    assert listed["total"] == 1
    assert listed["has_shared"] is False
    hello = listed["items"][0]
    assert hello["task_id"] == "hello"
    assert hello["has_readme"] is False
    assert hello["job_count"] == 0
    assert hello["last_status"] is None
    empty = svc.list_tasks(
        dataset_id="test/publish-min",
        auth=auth,
        package_digest=digest,
        limit=50,
        offset=50,
    )
    assert empty["items"] == []
    assert empty["total"] == 1
    assert listed["overlay_prefixes"] == []
    matched = svc.list_tasks(
        dataset_id="test/publish-min",
        auth=auth,
        package_digest=digest,
        q="HEL",
    )
    assert [item["task_id"] for item in matched["items"]] == ["hello"]
    missed = svc.list_tasks(
        dataset_id="test/publish-min",
        auth=auth,
        package_digest=digest,
        q="missing",
    )
    assert missed["items"] == []
    assert missed["total"] == 0


def test_list_tasks_skips_blob_after_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive, _raw = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.publish(meta=meta, archive=archive, auth=auth)

    def _no_blob(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("list_tasks must not read the package blob")

    monkeypatch.setattr("services.registry.package_service.read_blob", _no_blob)
    listed = svc.list_tasks(
        dataset_id="test/publish-min",
        auth=auth,
        package_digest=str(payload["package_digest"]),
        limit=20,
        offset=0,
    )
    assert listed["items"][0]["task_id"] == "hello"
    assert listed["overlay_prefixes"] == []


def test_list_tasks_reads_variant_profile_overlays(tmp_path: Path) -> None:
    import shutil

    from services.registry.package_files import (
        build_index_from_archive,
        is_profiles_document,
        overlay_paths_from_profiles_yaml,
    )

    assert is_profiles_document("profiles.yaml") is True
    assert is_profiles_document("profiles.docker.yaml") is True
    assert is_profiles_document("env/profiles.ssh.yaml") is True
    assert is_profiles_document("tasks/hello/profiles.yaml") is False
    assert is_profiles_document("shared/note.yaml") is False
    assert overlay_paths_from_profiles_yaml(
        'agent_profiles:\n  x:\n    overlays:\n      - overlays/docker\n      - "overlays/ssh"\n'
    ) == ["overlays/docker", "overlays/ssh"]

    root = tmp_path / "pkg"
    shutil.copytree(FIXTURE, root)
    (root / "profiles.docker.yaml").write_text(
        "format: ageval.profiles/1\n"
        "agent_profiles:\n"
        "  docker:\n"
        "    executor: acp\n"
        "    overlays:\n"
        "      - overlays/docker\n",
        encoding="utf-8",
    )
    (root / "overlays").mkdir()
    (root / "overlays" / "docker").write_text("x\n", encoding="utf-8")
    archive, blob_digest, size = build_archive(root)
    index = build_index_from_archive(archive, package_digest="sha256:overlay")
    assert index.overlay_prefixes == ["overlays/docker"]

    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    path = tmp_path / "overlay-pkg.tar.gz"
    path.write_bytes(archive)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = svc.publish(
        meta={
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "package_digest": compute_package_digest(root),
            "blob_digest": blob_digest,
            "media_type": MEDIA_TYPE,
            "visibility": "private",
            "org_id": "acme",
            "size": size,
        },
        archive=path,
        auth=auth,
    )
    listed = svc.list_tasks(
        dataset_id="test/publish-min",
        auth=auth,
        package_digest=str(payload["package_digest"]),
        limit=20,
        offset=0,
    )
    assert listed["overlay_prefixes"] == ["overlays/docker"]
