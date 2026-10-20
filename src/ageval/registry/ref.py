"""PackageRef parsing for local paths and registry coordinates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ageval.config.dataset import validate_dataset_id
from ageval.config.errors import ConfigError

# identity@version  OR  identity@sha256:<64hex>
_REF_RE = re.compile(r"^(?P<id>[^@]+)@(?P<tail>.+)$")
_DIGEST_TAIL_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


_BRANCH_NAMES = frozenset({"main", "master", "head", "develop", "dev", "trunk", "canary"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GIT_HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_SSH_GIT_RE = re.compile(
    rf"^git@(?P<host>{_GIT_HOST_RE.pattern}):(?P<path>[A-Za-z0-9][A-Za-z0-9._/-]*)$"
)
REGISTRY_GIT_URL_MESSAGE = "git_url must be an https URL without userinfo, or git@host:path"


def _validate_subdir(subdir: str | None, *, location: str) -> str | None:
    if subdir is None:
        return None
    text = subdir.strip().replace("\\", "/").strip("/")
    if not text:
        raise ConfigError("invalid_package", "empty #subdir in git ref", location=location)
    if text.startswith("/") or ".." in Path(text).parts:
        raise ConfigError(
            "invalid_package", "#subdir must be repo-relative without '..'", location=location
        )
    return text


def _validate_git_ref(ref: str, *, location: str) -> str:
    text = ref.strip()
    if not text or "@" in text or "#" in text or any(ch.isspace() for ch in text):
        raise ConfigError("invalid_package", "git ref requires @<tag|full-sha>", location=location)
    if text.casefold() in _BRANCH_NAMES or text.startswith("refs/"):
        raise ConfigError(
            "invalid_package",
            f"mutable branch ref {text!r} is not allowed; pin a tag or full commit sha",
            location=location,
        )
    if _SHA_RE.fullmatch(text):
        return text
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", text) or text.endswith(("/", ".")):
        raise ConfigError("invalid_package", f"invalid git tag ref: {text!r}", location=location)
    return text


def _parse_git_ref(text: str) -> PackageRef | None:
    """Return a git PackageRef, or None when *text* is not a git source."""
    is_github = text.startswith("github:")
    is_url = text.startswith(("https://", "http://", "file://", "git@"))
    if not is_github and not is_url:
        return None
    body, hash_sep, subdir_raw = text.partition("#")
    subdir = _validate_subdir(subdir_raw if hash_sep else None, location=text)
    if is_github:
        coord = body[len("github:") :]
        head, at, ref = coord.rpartition("@")
        if not at:
            raise ConfigError("invalid_package", "git ref requires @<tag|full-sha>", location=text)
        parts = [p for p in head.split("/") if p]
        if len(parts) != 2 or not all(_GIT_SEGMENT_RE.fullmatch(p) for p in parts):
            raise ConfigError(
                "invalid_package", "github: ref must be github:org/repo@<tag|sha>", location=text
            )
        repo = parts[1].removesuffix(".git")
        git_url = f"https://github.com/{parts[0]}/{repo}.git"
        pinned = _validate_git_ref(ref, location=text)
        return PackageRef(kind="git", git_url=git_url, git_ref=pinned, subdir=subdir)
    head, at, ref = body.rpartition("@")
    if not at:
        raise ConfigError("invalid_package", "git ref requires @<tag|full-sha>", location=text)
    git_url = head.strip()
    if not git_url:
        raise ConfigError("invalid_package", "empty git url in ref", location=text)
    # Credentials never enter the lock. Token-as-username (`https://<pat>@host`)
    # has password=None, so any userinfo is rejected. location stays off the raw
    # URL so the token is not echoed.
    if _url_has_userinfo(git_url):
        raise ConfigError(
            "invalid_package",
            "git URL must not embed credentials; use local git credentials",
        )
    pinned = _validate_git_ref(ref, location=text)
    return PackageRef(kind="git", git_url=git_url, git_ref=pinned, subdir=subdir)


@dataclass(frozen=True, slots=True)
class PackageRef:
    """Either a local Dataset path or a registry coordinate."""

    kind: str  # "path" | "version" | "digest" | "git"
    path: Path | None = None
    dataset_id: str | None = None
    version: str | None = None
    package_digest: str | None = None
    git_url: str | None = None
    git_ref: str | None = None
    subdir: str | None = None

    def display(self) -> str:
        if self.kind == "path":
            return str(self.path)
        if self.kind == "git":
            base = f"{self.git_url}@{self.git_ref}"
            return f"{base}#{self.subdir}" if self.subdir else base
        if self.kind == "version":
            return f"{self.dataset_id}@{self.version}"
        return f"{self.dataset_id}@{self.package_digest}"


def _url_has_userinfo(git_url: str) -> bool:
    parsed = urlparse(git_url)
    return parsed.username is not None or parsed.password is not None


def _git_path_ok(path: str) -> bool:
    if not path or path.startswith(("/", "-")) or path.endswith("/"):
        return False
    parts = path.split("/")
    return all(part not in {"", ".", ".."} and not part.startswith("-") for part in parts)


def validate_registry_git_url(git_url: str) -> str:
    """Accept an https URL without userinfo, or ``git@host:path``.

    Registry storage and ``git ls-remote`` share this check. ``file://``,
    ``ext::``, option-shaped values, and ``javascript:`` are rejected.
    """
    if (
        not git_url
        or git_url.strip() != git_url
        or any(ord(ch) < 33 or ch in "%\\?#@" for ch in git_url.removeprefix("git@"))
    ):
        raise ValueError(REGISTRY_GIT_URL_MESSAGE)
    if git_url.startswith("git@"):
        match = _SSH_GIT_RE.fullmatch(git_url)
        if match is None or ".." in match.group("host") or not _git_path_ok(match.group("path")):
            raise ValueError(REGISTRY_GIT_URL_MESSAGE)
        return git_url
    parsed = urlparse(git_url)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError(REGISTRY_GIT_URL_MESSAGE) from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(REGISTRY_GIT_URL_MESSAGE)
    path = parsed.path
    path_ok = path in {"", "/"} or (path.startswith("/") and _git_path_ok(path[1:]))
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or _GIT_HOST_RE.fullmatch(host) is None
        or ".." in host
        or parsed.query
        or parsed.fragment
        or parsed.params
        or not path_ok
    ):
        raise ValueError(REGISTRY_GIT_URL_MESSAGE)
    return git_url


def parse_package_ref(raw: str | Path, *, cwd: Path | None = None) -> PackageRef:
    """Parse a CLI path/ref argument into a PackageRef.

    Existing directories are always treated as local paths (even if the string
    contains ``@``). Registry refs use ``dataset_id@version`` or
    ``dataset_id@sha256:<hex>``.
    """
    if isinstance(raw, Path):
        path = raw.expanduser()
        if not path.is_absolute() and cwd is not None:
            path = (cwd / path).resolve(strict=False)
        else:
            path = path.resolve(strict=False)
        if path.is_dir():
            return PackageRef(kind="path", path=path)
        raise ConfigError(
            "invalid_package",
            f"path is not a directory: {raw}",
            location=str(raw),
        )

    text = str(raw).strip()
    if not text:
        raise ConfigError("invalid_package", "empty package ref", location=str(raw))

    git_ref = _parse_git_ref(text)
    if git_ref is not None:
        return git_ref

    # Prefer local path when it exists as a directory.
    candidate = Path(text).expanduser()
    base = cwd or Path.cwd()
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)
    if candidate.is_dir():
        return PackageRef(kind="path", path=candidate)

    m = _REF_RE.match(text)
    if not m:
        raise ConfigError(
            "invalid_package",
            "expected local Dataset path or <dataset_id>@<version|sha256:…>",
            location=text,
        )
    dataset_id = m.group("id")
    tail = m.group("tail")
    try:
        validate_dataset_id(dataset_id)
    except ConfigError as exc:
        raise ConfigError(
            "invalid_package",
            f"invalid dataset_id in ref: {exc.message}",
            location=text,
        ) from exc

    dm = _DIGEST_TAIL_RE.match(tail)
    if dm:
        return PackageRef(
            kind="digest",
            dataset_id=dataset_id,
            package_digest=f"sha256:{dm.group(1)}",
        )
    if not tail or "/" in tail and tail.startswith("sha256:"):
        raise ConfigError(
            "invalid_package",
            "invalid digest tail in package ref",
            location=text,
        )
    # version is opaque non-empty string (no @)
    if "@" in tail or not tail.strip():
        raise ConfigError(
            "invalid_package",
            "invalid version in package ref",
            location=text,
        )
    return PackageRef(kind="version", dataset_id=dataset_id, version=tail)
