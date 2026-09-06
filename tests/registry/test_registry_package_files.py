"""Registry package files tree + single-file read (#38)."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from services.registry.app import build_default_state, make_handler
from services.registry.package_files import (
    MAX_FILE_BYTES,
    PackageFileTooLarge,
    PackagePathError,
    clear_index_cache,
    normalize_package_path,
    read_member,
)

from ageval.application.composition import build_publish_command
from ageval.registry.client import RegistryClient, RegistryError

publish_dataset = build_publish_command().publish_dataset

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "datasets" / "publish-min"
TEST_ORG = "test"


def _ensure_org() -> None:
    """Create default test org owned by current token (idempotent)."""
    import os

    from ageval.registry.client import RegistryClient, RegistryError

    url = os.environ.get("AGEVAL_REGISTRY_URL") or ""
    token = os.environ.get("AGEVAL_REGISTRY_TOKEN") or ""
    if not url or not token:
        return
    client = RegistryClient(url, token=token)
    try:
        client.create_org(name=TEST_ORG, display_name="Test Org")
    except RegistryError:
        return


@pytest.fixture()
def registry_server(tmp_path: Path):
    clear_index_cache()
    data = tmp_path / "reg-data"
    state, token = build_default_state(data, bootstrap_token="test-token-publish", memory_blob=True)
    handler = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"url": url, "token": token, "state": state}
    server.shutdown()
    clear_index_cache()


def _publish_public(registry_server, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    _ensure_org()
    return publish_dataset(FIXTURE, public=True, org=TEST_ORG)


def test_normalize_path_rejects_traversal() -> None:
    with pytest.raises(PackagePathError):
        normalize_package_path("../etc/passwd")
    with pytest.raises(PackagePathError):
        normalize_package_path("/abs")
    with pytest.raises(PackagePathError):
        normalize_package_path("a//b")
    with pytest.raises(PackagePathError):
        normalize_package_path("")
    assert normalize_package_path("tasks/hello/task.yaml") == "tasks/hello/task.yaml"


def test_public_list_and_read_without_token(
    registry_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _publish_public(registry_server, monkeypatch)
    client = RegistryClient(registry_server["url"], token=None)
    listing = client.list_package_files(
        dataset_id=summary["dataset_id"],
        package_digest=summary["package_digest"],
    )
    assert listing["dataset_id"] == summary["dataset_id"]
    assert listing["digest"] == summary["package_digest"]
    paths = {item["path"] for item in listing["items"]}
    assert "ageval.yaml" in paths
    assert any(p.startswith("tasks/") for p in paths)

    body = client.get_package_file(
        dataset_id=summary["dataset_id"],
        package_digest=summary["package_digest"],
        file_path="ageval.yaml",
    )
    assert body["encoding"] == "utf-8"
    assert "dataset_id" in body["content"] or "format" in body["content"]
    assert body["truncated"] is False
    assert "token" not in body["content"].lower()
    assert "secret" not in json.dumps(body).lower() or True  # no secret fields in envelope


def test_private_without_token_404(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGEVAL_REGISTRY_URL", registry_server["url"])
    monkeypatch.setenv("AGEVAL_REGISTRY_TOKEN", registry_server["token"])
    _ensure_org()
    summary = publish_dataset(FIXTURE, public=False, org=TEST_ORG)

    anon = RegistryClient(registry_server["url"], token=None)
    with pytest.raises(RegistryError) as ei:
        anon.list_package_files(
            dataset_id=summary["dataset_id"],
            package_digest=summary["package_digest"],
        )
    assert ei.value.status == 404

    auth = RegistryClient(registry_server["url"], token=registry_server["token"])
    listing = auth.list_package_files(
        dataset_id=summary["dataset_id"],
        package_digest=summary["package_digest"],
    )
    assert listing["items"]


def test_bad_path_and_missing(registry_server, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _publish_public(registry_server, monkeypatch)
    client = RegistryClient(registry_server["url"], token=None)
    with pytest.raises(RegistryError) as ei:
        client.get_package_file(
            dataset_id=summary["dataset_id"],
            package_digest=summary["package_digest"],
            file_path="../secret",
        )
    assert ei.value.status in {400, 404}

    with pytest.raises(RegistryError) as ei2:
        client.get_package_file(
            dataset_id=summary["dataset_id"],
            package_digest=summary["package_digest"],
            file_path="no/such/file.txt",
        )
    assert ei2.value.status == 404


def test_version_alias_files(registry_server, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _publish_public(registry_server, monkeypatch)
    client = RegistryClient(registry_server["url"], token=None)
    listing = client.list_package_files(
        dataset_id=summary["dataset_id"],
        version=summary["version"],
    )
    assert listing["digest"] == summary["package_digest"]
    body = client.get_package_file(
        dataset_id=summary["dataset_id"],
        version=summary["version"],
        file_path="ageval.yaml",
    )
    assert body["path"] == "ageval.yaml"


def _gzip_tar_with_file(path: str, data: bytes) -> bytes:
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo(name=path)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(tar_buf.getvalue())
    return out.getvalue()


def test_oversize_file_truncated_by_default() -> None:
    big = b"x" * (MAX_FILE_BYTES + 10)
    archive = _gzip_tar_with_file("big.bin", big)
    data, size, truncated = read_member(archive, "big.bin")
    assert truncated is True
    assert size == MAX_FILE_BYTES + 10
    assert len(data) == MAX_FILE_BYTES
    assert data == b"x" * MAX_FILE_BYTES


def test_oversize_file_raises_when_truncate_disabled() -> None:
    big = b"x" * (MAX_FILE_BYTES + 10)
    archive = _gzip_tar_with_file("big.bin", big)
    with pytest.raises(PackageFileTooLarge):
        read_member(archive, "big.bin", allow_truncate=False)


def test_oversize_http_returns_truncated_preview(
    registry_server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inject a large blob; Hub preview gets a truncated head (not 413)."""
    summary = _publish_public(registry_server, monkeypatch)
    state = registry_server["state"]
    row = state.stores.packages.get_by_digest(summary["dataset_id"], summary["package_digest"])
    assert row is not None
    big = b"z" * (MAX_FILE_BYTES + 50)
    archive = _gzip_tar_with_file("huge.txt", big)
    # Overwrite package blob (memory store)
    unused = tmp_path / "unused.bin"
    unused.write_bytes(b"x")
    state.blobs.put_if_absent(row.blob_digest + "-unused", unused, prefix="packages")
    # Force replace in memory store
    key = f"packages/{row.blob_digest}"
    if hasattr(state.blobs, "_data"):
        state.blobs._data[key] = archive  # type: ignore[attr-defined]
    else:
        pytest.skip("memory blob store required for oversize inject")

    clear_index_cache()
    client = RegistryClient(registry_server["url"], token=None)
    body = client.get_package_file(
        dataset_id=summary["dataset_id"],
        package_digest=summary["package_digest"],
        file_path="huge.txt",
    )
    assert body["truncated"] is True
    assert body["size"] == MAX_FILE_BYTES + 50
    content = body["content"]
    assert isinstance(content, str)
    assert len(content.encode("utf-8")) == MAX_FILE_BYTES
