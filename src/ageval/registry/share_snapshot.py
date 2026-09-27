"""Snapshot-share blob marker, secret scan, and pre-upload scrub.

The blob is not a Config format. Config Core does not read it.
Catalog upload rejects any gzip archive that contains the marker.
"""

from __future__ import annotations

import gzip
import json
import re
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

SNAPSHOT_SHARE_KIND = "snapshot-share"
SNAPSHOT_SHARE_MARKER = "snapshot-share.json"
SHARE_BLOB_PREFIX = "shares"
LIVE_SHARE_SIDECAR = "live-share.json"

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


def text_has_plaintext_secret(chunk: bytes) -> bool:
    """True when a text chunk assigns a plaintext secret or embeds a private key."""
    if b"\x00" in chunk:
        return False
    if _PRIVATE_KEY.search(chunk):
        return True
    for match in _ASSIGNED_VALUE.finditer(chunk):
        if _value_is_plaintext_secret(match.group("value")):
            return True
    return False


class ShareArchiveTooLarge(Exception):
    """Decompressed members exceed the caller's byte cap."""


def snapshot_has_plaintext_secret(archive: Path) -> bool:
    """Scan decompressed text members for a secret assigned to a known key.

    Reads at most 4 MiB total. A later member is not loaded into memory.
    """
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
                if text_has_plaintext_secret(chunk):
                    return True
    except (OSError, tarfile.TarError, gzip.BadGzipFile, EOFError):
        return False
    return False


def iter_archive_files(archive: Path, *, max_total: int) -> Iterator[tuple[str, bytes]]:
    """Yield ``(normalized path, bytes)`` without reading past ``max_total``."""
    seen = 0
    with _open_tar(archive) as tar:
        for info in tar.getmembers():
            if not info.isfile():
                continue
            extracted = tar.extractfile(info)
            if extracted is None:
                continue
            budget = max_total - seen
            data = extracted.read(budget + 1)
            if len(data) > budget:
                raise ShareArchiveTooLarge(max_total)
            seen += len(data)
            yield _norm_name(info.name), data


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


_SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "api_token",
        "access_token",
        "authorization",
        "password",
        "client_secret",
        "refresh_token",
        "bearer_token",
    }
)
_TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".txt",
    ".md",
    ".toml",
    ".log",
    ".env",
    ".cfg",
    ".ini",
}
_LOCATOR_TEXT = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_ENV_NAME_TEXT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_TOKEN_VALUE = re.compile(r"^(?:sk-|ghp_|github_pat_|AKIA)")
_TEXT_ASSIGN = re.compile(
    r"""(?ix)
    (?P<prefix>
      ["']?
      (?:api_key|apikey|api_token|access_token|authorization|password|client_secret|refresh_token|bearer_token)
      ["']?
      \s*[:=]\s*
      ["']?
    )
    (?P<value>[^"'\n\r]{1,300}?)
    (?P<suffix>["']?)
    (?=\s*[,}\n\r]|$)
    """
)


def _keep_secret_value(value: str) -> bool:
    text = value.strip()
    if not text or text == "[redacted]" or _LOCATOR_TEXT.fullmatch(text):
        return True
    return _ENV_NAME_TEXT.fullmatch(text) is not None


def scrub_structure(value: Any, *, key: str = "") -> Any:
    """Replace detected secret values. Locators and env names stay."""
    if isinstance(value, dict):
        return {
            str(item_key): scrub_structure(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_structure(item, key=key) for item in value]
    if isinstance(value, str) and key.casefold() in _SECRET_KEY_NAMES:
        return value if _keep_secret_value(value) else "[redacted]"
    if isinstance(value, str) and _TOKEN_VALUE.match(value):
        return "[redacted]"
    return value


def scrub_text(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group("value").strip()
        if _keep_secret_value(value):
            return match.group(0)
        return match.group("prefix") + "[redacted]" + match.group("suffix")

    return _TEXT_ASSIGN.sub(repl, text)


def scrub_file(path: Path) -> None:
    """Rewrite one text file in place. Callers pass a copy, not the suite dir."""
    suffix = path.suffix.lower()
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if suffix == ".json":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            updated = scrub_text(raw)
        else:
            updated = json.dumps(scrub_structure(parsed), indent=2, sort_keys=True) + "\n"
            updated = scrub_text(updated)
    elif suffix == ".jsonl":
        lines: list[str] = []
        for line in raw.splitlines():
            if not line.strip():
                lines.append(line)
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                lines.append(scrub_text(line))
            else:
                lines.append(
                    json.dumps(scrub_structure(parsed), sort_keys=True, ensure_ascii=False)
                )
        updated = "\n".join(lines) + ("\n" if raw.endswith("\n") else "")
    elif suffix in {".yaml", ".yml"}:
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError:
            updated = scrub_text(raw)
        else:
            updated = yaml.safe_dump(scrub_structure(parsed), sort_keys=False)
            updated = scrub_text(updated)
    elif suffix in _TEXT_SUFFIXES:
        updated = scrub_text(raw)
    else:
        return
    if updated != raw:
        path.write_text(updated, encoding="utf-8")


def scrub_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
            scrub_file(path)


def scrub_member_bytes(name: str, data: bytes) -> bytes:
    """Return scrubbed bytes for one archive member. Non-text members pass through."""
    suffix = Path(name).suffix.lower()
    if suffix not in _TEXT_SUFFIXES or b"\x00" in data:
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ageval-scrub-") as tmp:
        path = Path(tmp) / f"member{suffix}"
        path.write_text(text, encoding="utf-8")
        scrub_file(path)
        return path.read_bytes()
