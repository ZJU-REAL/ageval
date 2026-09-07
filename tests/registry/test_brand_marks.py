"""Package icon_key / icon_github: allowlist, GitHub login, PATCH."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.brand_marks import ALLOWED_KEYS, normalize_icon_github
from services.registry.errors import RegistryAppError
from services.registry.package_service import PackageService
from services.registry.store import MemoryBlobStore, TokenInfo
from services.registry.store_schema import (
    open_sqlite_stores,
)

from ageval.registry.archive import MEDIA_TYPE, build_archive
from ageval.registry.digest import compute_package_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
ASSETS = REPO / "apps/hub/src/lib/brand-marks/assets"


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


def _meta_archive(tmp_path: Path) -> tuple[dict[str, object], Path]:
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
    )


def test_hub_catalog_keys_match_assets() -> None:
    allow = json.loads(
        (REPO / "services/registry/brand_marks.json").read_text(encoding="utf-8"),
    )
    ts = (REPO / "apps/hub/src/lib/brand-marks/catalog.ts").read_text(encoding="utf-8")
    ids = re.findall(r'id: "([a-z0-9-]+)"', ts)
    files = re.findall(r'file: "([^"]+)"', ts)
    assert sorted(allow) == sorted(ids)
    assert frozenset(allow) == ALLOWED_KEYS
    for name in files:
        assert (ASSETS / name).is_file(), name
        assert (ASSETS / name).stat().st_size > 80, name


def test_normalize_icon_github() -> None:
    assert normalize_icon_github("https://github.com/e2b-dev/E2B") == "e2b-dev"
    assert normalize_icon_github("octocat") == "octocat"
    with pytest.raises(RegistryAppError) as ei:
        normalize_icon_github("not a login")
    assert ei.value.error == "invalid_request"


def test_patch_icon_roundtrip(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.orgs.create_org(name="acme", owner_user_id="alice", display_name="Acme")
    meta, archive = _meta_archive(tmp_path)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    svc.publish(meta=meta, archive=archive, auth=auth)

    stored = svc.patch_marketplace(
        dataset_id="test/publish-min",
        auth=auth,
        icon_key="docker",
        icon_github="",
        has_icon_key=True,
        has_icon_github=True,
    )
    assert stored["icon_key"] == "docker"
    assert "icon_github" not in stored

    gh = svc.patch_marketplace(
        dataset_id="test/publish-min",
        auth=auth,
        icon_key="",
        icon_github="https://github.com/octocat",
        has_icon_key=True,
        has_icon_github=True,
    )
    assert "icon_key" not in gh
    assert gh["icon_github"] == "octocat"

    listed = svc.list_packages(
        auth=auth,
        prefix=None,
        visibility=None,
        version=None,
        package_kind=None,
    )
    row = next(i for i in listed["items"] if i["dataset_id"] == "test/publish-min")
    assert row["icon_github"] == "octocat"
    assert row.get("uploaded_by") == "alice"

    cleared = svc.patch_marketplace(
        dataset_id="test/publish-min",
        auth=auth,
        icon_key="",
        icon_github="",
        has_icon_key=True,
        has_icon_github=True,
    )
    assert "icon_key" not in cleared
    assert "icon_github" not in cleared

    with pytest.raises(RegistryAppError) as ei:
        svc.patch_marketplace(
            dataset_id="test/publish-min",
            auth=auth,
            icon_key="not-a-brand",
            has_icon_key=True,
        )
    assert ei.value.error == "invalid_request"
