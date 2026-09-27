"""Snapshot-share blob marker and secret scan.

The blob is not a Config format. Config Core does not read it.
Catalog upload rejects any gzip archive that contains the marker.
"""

from __future__ import annotations

import gzip
import re
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SNAPSHOT_SHARE_KIND = "snapshot-share"
SNAPSHOT_SHARE_MARKER = "snapshot-share.json"
SHARE_BLOB_PREFIX = "shares"

_SECRET_KEYS = (
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "authorization",
    "password",
    "client_secret",
    "refresh_token",
    "bearer_token",
)
_ASSIGNED_VALUE = re.compile(
    rb"""(?ix)
    ["']?
    (?:"""
    + "|".join(_SECRET_KEYS).encode()
    + rb""")
    ["']?
    \s*[:=]\s*
    ["']?
    (?P<value>[^"'\n\r]{1,300}?)
    ["']?
    (?=\s*[,}\n\r]|$)
    """
)
_PRIVATE_KEY = re.compile(rb"(?i)-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")
_LOCATOR = re.compile(rb"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_ENV_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _norm_name(name: str) -> str:
    if name.startswith("./"):
        return name[2:]
    return name


def _marker_name(name: str) -> bool:
    return _norm_name(name) == SNAPSHOT_SHARE_MARKER


@contextmanager
def _open_tar(path: Path) -> Iterator[tarfile.TarFile]:
    with (
        path.open("rb") as fh,
        gzip.GzipFile(fileobj=fh, mode="rb") as gz,
        tarfile.open(fileobj=gz, mode="r:") as tar,
    ):
        yield tar


def archive_contains_snapshot_marker(archive: Path) -> bool:
    """True when the gzip tar has ``snapshot-share.json`` at the archive root."""
    try:
        with _open_tar(archive) as tar:
            return any(_marker_name(info.name) for info in tar.getmembers())
    except (OSError, tarfile.TarError, gzip.BadGzipFile, EOFError):
        return False


def _value_is_plaintext_secret(value: bytes) -> bool:
    text = value.strip()
    if not text or text == b"[redacted]" or _LOCATOR.fullmatch(text):
        return False
    return _ENV_NAME.fullmatch(text) is None


def snapshot_has_plaintext_secret(archive: Path) -> bool:
    """Scan decompressed text members for a secret assigned to a known key."""
    try:
        with _open_tar(archive) as tar:
            seen = 0
            for info in tar.getmembers():
                if not info.isfile() or seen >= 4_000_000:
                    continue
                extracted = tar.extractfile(info)
                if extracted is None:
                    continue
                chunk = extracted.read(min(int(info.size), 4_000_000 - seen))
                seen += len(chunk)
                if b"\x00" in chunk:
                    continue
                if _PRIVATE_KEY.search(chunk):
                    return True
                for match in _ASSIGNED_VALUE.finditer(chunk):
                    if _value_is_plaintext_secret(match.group("value")):
                        return True
    except (OSError, tarfile.TarError, gzip.BadGzipFile, EOFError):
        return False
    return False


def read_archive_member(archive: Path, member: str, *, max_bytes: int = 2_000_000) -> bytes | None:
    """Return one file member, or None when it is absent."""
    with _open_tar(archive) as tar:
        try:
            info = tar.getmember(member)
        except KeyError:
            return None
        if not info.isfile():
            return None
        extracted = tar.extractfile(info)
        if extracted is None:
            return None
        return extracted.read(max_bytes)


def archive_member_names(archive: Path) -> list[str]:
    with _open_tar(archive) as tar:
        return [_norm_name(info.name) for info in tar.getmembers()]
