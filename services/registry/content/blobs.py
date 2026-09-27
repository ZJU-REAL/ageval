"""Blob content stores: memory (tests), filesystem (dev), S3-compatible (compose)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Blob
# ---------------------------------------------------------------------------


class MemoryBlobStore:
    """Unit-test only blob backend (bytes adapter behind a Path/fileobj put)."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def _key(self, blob_digest: str, prefix: str) -> str:
        return f"{prefix}/{blob_digest}"

    def put_if_absent(
        self, blob_digest: str, source: Path | Any, *, prefix: str = "packages"
    ) -> None:
        payload = source.read_bytes() if isinstance(source, Path) else source.read()
        with self._lock:
            self._data.setdefault(self._key(blob_digest, prefix), payload)

    def open(self, blob_digest: str, *, prefix: str = "packages") -> Any:
        import io

        with self._lock:
            data = self._data.get(self._key(blob_digest, prefix))
        if data is None:
            return None
        return io.BytesIO(data)

    def size(self, blob_digest: str, *, prefix: str = "packages") -> int | None:
        with self._lock:
            data = self._data.get(self._key(blob_digest, prefix))
        return None if data is None else len(data)

    def delete(self, blob_digest: str, *, prefix: str = "packages") -> bool:
        """Remove blob if present. Returns True when a key was deleted."""
        with self._lock:
            return self._data.pop(self._key(blob_digest, prefix), None) is not None


class FilesystemBlobStore:
    """Dev fallback: local directory. Prefer S3 for compose e2e."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, blob_digest: str, prefix: str) -> Path:
        key = blob_digest.replace(":", "_")
        return self.root / prefix / key

    def put_if_absent(
        self, blob_digest: str, source: Path | Any, *, prefix: str = "packages"
    ) -> None:
        import shutil

        path = self._path(blob_digest, prefix)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            if isinstance(source, Path):
                shutil.copyfile(source, tmp)
            else:
                with tmp.open("wb") as out:
                    shutil.copyfileobj(source, out)
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def open(self, blob_digest: str, *, prefix: str = "packages") -> Any:
        path = self._path(blob_digest, prefix)
        if not path.is_file():
            return None
        return path.open("rb")

    def size(self, blob_digest: str, *, prefix: str = "packages") -> int | None:
        path = self._path(blob_digest, prefix)
        if not path.is_file():
            return None
        return path.stat().st_size

    def delete(self, blob_digest: str, *, prefix: str = "packages") -> bool:
        path = self._path(blob_digest, prefix)
        if not path.is_file():
            return False
        path.unlink()
        return True


class S3BlobStore:
    """S3-compatible blob store (RustFS / AWS). Credentials stay server-side only."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        try:
            import boto3
            from botocore.client import Config
            from botocore.exceptions import ClientError
        except ImportError as exc:
            raise RuntimeError(
                "boto3 required for S3 blob backend; install with: uv sync --extra registry"
            ) from exc
        self._ClientError = ClientError
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint.rstrip("/"),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        import contextlib

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except self._ClientError:
            with contextlib.suppress(self._ClientError):
                self._client.create_bucket(Bucket=self.bucket)

    def _object_key(self, blob_digest: str, prefix: str) -> str:
        return f"{prefix}/{blob_digest.replace(':', '_')}"

    def put_if_absent(
        self, blob_digest: str, source: Path | Any, *, prefix: str = "packages"
    ) -> None:
        key = self._object_key(blob_digest, prefix)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return
        except self._ClientError:
            pass
        if isinstance(source, Path):
            self._client.upload_file(str(source), self.bucket, key)
            return
        self._client.upload_fileobj(source, self.bucket, key)

    def open(self, blob_digest: str, *, prefix: str = "packages") -> Any:
        key = self._object_key(blob_digest, prefix)
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
        except self._ClientError:
            return None
        return resp["Body"]

    def size(self, blob_digest: str, *, prefix: str = "packages") -> int | None:
        key = self._object_key(blob_digest, prefix)
        try:
            resp = self._client.head_object(Bucket=self.bucket, Key=key)
        except self._ClientError:
            return None
        return int(resp["ContentLength"])

    def delete(self, blob_digest: str, *, prefix: str = "packages") -> bool:
        key = self._object_key(blob_digest, prefix)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except self._ClientError:
            return False
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except self._ClientError:
            return False
        return True
