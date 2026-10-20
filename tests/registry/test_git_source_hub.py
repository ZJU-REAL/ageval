"""Source-only Hub registration + suite attribution (#305)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from services.registry.access import AccessPolicy
from services.registry.auth.tokens import TokenInfo
from services.registry.content.blobs import MemoryBlobStore
from services.registry.db.schema import open_sqlite_stores
from services.registry.errors import RegistryAppError
from services.registry.packages.service import PackageService
from services.registry.results.service import ResultService
from typer.testing import CliRunner

from ageval.cli.main import app
from ageval.registry.digest import compute_eval_digest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
DIGEST = compute_eval_digest(FIXTURE)
COMMIT = "a" * 40


def _services(tmp_path: Path) -> tuple[PackageService, ResultService]:
    meta = open_sqlite_stores(tmp_path / "meta.sqlite3")
    blobs = MemoryBlobStore()
    access = AccessPolicy(orgs=meta.orgs, packages=meta.packages, results=meta.results)
    packages = PackageService(meta.packages, meta.orgs, blobs, access, max_upload=64 * 1024 * 1024)
    results = ResultService(
        meta.results,
        meta.packages,
        meta.orgs,
        meta.inbox,
        blobs,
        access,
        max_upload=64 * 1024 * 1024,
    )
    return packages, results


def _ensure_org(packages: PackageService) -> None:
    if packages.orgs.get_org("test") is None:
        packages.orgs.create_org(name="test", owner_user_id="alice", display_name="Test")


def _register(packages: PackageService, *, digest: str = DIGEST) -> dict:
    _ensure_org(packages)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    return packages.register_source(
        body={
            "dataset_id": "test/publish-min",
            "version": "0.1.0",
            "git_url": "https://github.com/org/repo.git",
            "commit": COMMIT,
            "eval_digest": digest,
            "task_ids": ["hello"],
        },
        auth=auth,
    )


def test_register_source_idempotent_and_conflict(tmp_path: Path) -> None:
    packages, _results = _services(tmp_path)
    payload = _register(packages)
    assert payload["source_only"] is True
    assert payload["commit"] == COMMIT
    assert _register(packages)["eval_digest"] == DIGEST
    with pytest.raises(RegistryAppError) as exc:
        _register(packages, digest="sha256:" + "b" * 64)
    assert exc.value.error == "eval_digest_mismatch"
    assert "bump version" in exc.value.message


def test_register_source_carries_prepare_review_fields(tmp_path: Path) -> None:
    packages, _results = _services(tmp_path)
    _ensure_org(packages)
    auth = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="alice")
    payload = packages.register_source(
        body={
            "dataset_id": "test/publish-min",
            "version": "0.2.0",
            "git_url": "https://github.com/org/repo.git",
            "commit": COMMIT,
            "eval_digest": DIGEST,
            "task_ids": ["hello"],
            "prepare": "prepare.sh",
            "assets": [{"path": "tasks/hello/data/clip.bin", "sha256": "c" * 64}],
        },
        auth=auth,
    )
    assert payload["prepare"] == "prepare.sh"
    assert payload["has_prepare"] is True
    assert payload["assets"][0]["path"] == "tasks/hello/data/clip.bin"
    meta = packages.serve_meta(
        dataset_id="test/publish-min", version="0.2.0", package_digest=None, auth=auth
    )
    assert meta["has_prepare"] is True


def test_register_source_requires_org_membership(tmp_path: Path) -> None:
    packages, _results = _services(tmp_path)
    _ensure_org(packages)
    bob = TokenInfo(scopes=frozenset({"registry:publish"}), user_id="bob")
    with pytest.raises(RegistryAppError) as exc:
        packages.register_source(
            body={
                "dataset_id": "test/publish-min",
                "version": "0.1.0",
                "git_url": "https://github.com/org/repo.git",
                "commit": COMMIT,
                "eval_digest": DIGEST,
                "task_ids": ["hello"],
            },
            auth=bob,
        )
    assert exc.value.error == "forbidden"


def test_serve_meta_source_only(tmp_path: Path) -> None:
    packages, _results = _services(tmp_path)
    _register(packages)
    auth = TokenInfo(scopes=frozenset(), user_id="bob")
    payload = packages.serve_meta(
        dataset_id="test/publish-min", version="0.1.0", package_digest=None, auth=auth
    )
    assert payload["source_only"] is True
    assert payload["git_url"].startswith("https://github.com/")
    versions = packages.list_versions(dataset_id="test/publish-min", auth=auth)
    assert [i["version"] for i in versions["items"]] == ["0.1.0"]


def _suite_meta(tmp_path: Path, suite_run_id: str, *, digest: str | None) -> tuple[dict, Path]:
    archive = f"suite-{suite_run_id}".encode()
    meta: dict[str, object] = {
        "suite_run_id": suite_run_id,
        "dataset_id": "test/publish-min",
        "dataset_version": "0.1.0",
        "visibility": "public",
        "blob_digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "size": len(archive),
        "pass_rate": 1.0,
        "mean_score": 1.0,
        "metrics": {},
        "task_refs": [{"task_id": "hello", "status": "PASS", "score": 1.0}],
    }
    if digest:
        meta["eval_digest"] = digest
    path = tmp_path / f"{suite_run_id}.bin"
    path.write_bytes(archive)
    return meta, path


def test_suite_attributed_to_registered_source(tmp_path: Path) -> None:
    packages, results = _services(tmp_path)
    _register(packages)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_meta(tmp_path, "suite_src", digest=DIGEST)
    payload = results.upload_suite(meta=meta, archive=archive, auth=auth)
    assert payload["bound_kind"] == "source"
    assert payload["complete"] is True


def test_suite_from_unregistered_source_not_ranked(tmp_path: Path) -> None:
    _packages, results = _services(tmp_path)
    auth = TokenInfo(scopes=frozenset({"results:upload"}), user_id="alice")
    meta, archive = _suite_meta(tmp_path, "suite_anon", digest=DIGEST)
    payload = results.upload_suite(meta=meta, archive=archive, auth=auth)
    assert payload["bound_kind"] == "unknown"
    assert payload["complete"] is False


def test_lock_summary_carries_eval_digest(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    shutil.copytree(FIXTURE, root)
    result = CliRunner().invoke(app, ["lock", str(root), "--task", "hello"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["eval_digest"] == compute_eval_digest(root)
    assert "source" not in payload
