"""Whole-object blob put/open is Path/fileobj, not bytes-only."""

from __future__ import annotations

from pathlib import Path

from services.registry.content.blob_io import read_blob, sha256_file
from services.registry.content.blobs import (
    FilesystemBlobStore,
    MemoryBlobStore,
)
from services.registry.spool import extract_multipart_archive, spool_body


def test_filesystem_put_tmp_rename_and_open(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    src = tmp_path / "src.bin"
    payload = b"hello-stream" * 1000
    src.write_bytes(payload)
    digest = sha256_file(src)
    store.put_if_absent(digest, src, prefix="packages")
    assert store.size(digest, prefix="packages") == len(payload)
    with store.open(digest, prefix="packages") as fh:
        assert fh.read() == payload
    # second put is a no-op
    src.write_bytes(b"changed")
    store.put_if_absent(digest, src, prefix="packages")
    assert read_blob(store, digest, prefix="packages") == payload


def test_memory_put_from_path(tmp_path: Path) -> None:
    store = MemoryBlobStore()
    src = tmp_path / "m.bin"
    src.write_bytes(b"mem")
    store.put_if_absent("sha256:x", src, prefix="results")
    assert store.size("sha256:x", prefix="results") == 3
    assert read_blob(store, "sha256:x", prefix="results") == b"mem"


def test_s3_stub_uses_upload_fileobj(tmp_path: Path) -> None:
    calls: list[str] = []

    class _Client:
        def head_object(self, **kwargs: object) -> None:
            raise KeyError("missing")

        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            calls.append(f"file:{filename}")
            Path(filename).read_bytes()

        def upload_fileobj(self, fileobj: object, bucket: str, key: str) -> None:
            calls.append("fileobj")

        def get_object(self, **kwargs: object) -> dict[str, object]:
            raise KeyError("missing")

        def head_bucket(self, **kwargs: object) -> None:
            return None

        def create_bucket(self, **kwargs: object) -> None:
            return None

        def delete_object(self, **kwargs: object) -> None:
            return None

    from services.registry.content.blobs import S3BlobStore

    store = object.__new__(S3BlobStore)
    store.bucket = "ageval"
    store._ClientError = KeyError  # type: ignore[assignment]
    store._client = _Client()  # type: ignore[assignment]
    src = tmp_path / "s3.bin"
    src.write_bytes(b"abc")
    store.put_if_absent("sha256:s3", src, prefix="packages")
    assert calls == [f"file:{src}"]


def test_spool_and_multipart_do_not_require_bytes_archive(tmp_path: Path) -> None:
    archive = b"ARCHIVE-BYTES-NOT-IN-RAM-CONTRACT"
    boundary = "ageval-test"
    meta = b'{"dataset_id":"a/b"}'
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="metadata"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode()
    body += meta
    body += (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="archive"; filename="p.tar.gz"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body += archive
    body += f"\r\n--{boundary}--\r\n".encode()
    spool = spool_body(
        __import__("io").BytesIO(body),
        length=len(body),
        max_bytes=1024 * 1024,
        dest_dir=tmp_path,
    )
    parsed_meta, archive_path = extract_multipart_archive(
        spool,
        f"multipart/form-data; boundary={boundary}",
        tmp_path,
    )
    assert parsed_meta["dataset_id"] == "a/b"
    assert archive_path.read_bytes() == archive
    assert archive_path.is_file()
