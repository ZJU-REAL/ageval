"""Static ACP entry registry.

Descriptors are data only. The runtime table is the packaged
``acp_entries.json`` plus ``$AGEVAL_HOME/acp-entries.json`` when that file
exists. A home row cannot replace a packaged id. Digest is stable over
logical fields (no host PATH, no ``source``).
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final, Literal

from ageval.plugins.contrib.acp.path_probe import probe_commands
from ageval.plugins.contrib.acp.usage_journal import UsageJournal, UsageJournalRecord
from ageval.plugins.paths import ageval_home

IntegrationMode = Literal[1, 2, 3]
ModelBinding = Literal["config-option", "entry-default-only"]
Readiness = Literal[
    "ready",
    "engine-missing",
    "adapter-missing",
    "entry-missing",
    "unsupported-platform",
]

_REGISTRY_RESOURCE = "acp_entries.json"
_HOME_FILENAME = "acp-entries.json"
_MAX_HOME_BYTES = 64 * 1024
_MAX_HOME_ENTRIES = 32
_INSTALL_PREFIX = "npm install -g "
_SECRET_FIELD_DENYLIST: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "token",
        "password",
        "secret",
        "authorization",
        "cookie",
        "auth_file",
        "credential",
    }
)
_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "entry_id",
        "integration_mode",
        "execution_mode",
        "engine_command",
        "engine_detect_commands",
        "engine_package",
        "engine_version",
        "acp_command",
        "acp_detect_commands",
        "acp_package",
        "acp_version",
        "install_command",
        "credential_env_names",
        "keyless_auth",
        "model_binding",
        "platforms",
        "fixed_env",
        "home_dirs",
        "keyless_auth_paths",
        "usage_journal",
    }
)
_REQUIRED_ENTRY_KEYS: Final[tuple[str, ...]] = (
    "entry_id",
    "integration_mode",
    "execution_mode",
    "engine_detect_commands",
    "acp_command",
    "acp_detect_commands",
    "acp_version",
    "install_command",
    "credential_env_names",
    "model_binding",
    "platforms",
)
_FIXED_ENV_DENY_EXACT: Final[frozenset[str]] = frozenset(
    {
        "HOME",
        "PATH",
        "CODEX_HOME",
        "API_KEY",
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "AUTHORIZATION",
        "COOKIE",
    }
)
_FIXED_ENV_DENY_SUFFIXES: Final[tuple[str, ...]] = (
    "_SECRET",
    "_TOKEN",
    "_KEY",
    "_PASSWORD",
)
_USER_AUTH_ROOTS: Final[frozenset[str]] = frozenset(
    {
        ".ssh",
        ".aws",
        ".gnupg",
        ".ageval",
        ".docker",
        ".config",
        ".local",
        ".cache",
        ".kube",
        ".azure",
        ".npm",
    }
)
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z][0-9A-Za-z.-]*)?$")
_PKG_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SCOPED_PKG_RE = re.compile(r"^@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
_CMD_WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_FLAG_RE = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9._+-]*$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_CREDENTIAL_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_UNPINNED_VERSION_RE = re.compile(r"^(?:x|x\.x|x\.x\.x)$")

EntrySource = Literal["package", "user"]
_CACHE: dict[str | None, dict[str, AcpEntryDescriptor]] = {}


class AcpRegistryError(Exception):
    """One registry failure. ``plugins`` does not import config."""

    def __init__(self, error_code: str, message: str, location: str | None = None) -> None:
        super().__init__(error_code, message, location)
        self.error_code = error_code
        self.message = message
        self.location = location

    def __str__(self) -> str:
        if self.location:
            return f"{self.error_code}: {self.message} ({self.location})"
        return f"{self.error_code}: {self.message}"


def _fail(error_code: str, message: str, location: str) -> AcpRegistryError:
    return AcpRegistryError(error_code, message, location)


@dataclass(frozen=True, slots=True)
class AcpEntryDescriptor:
    entry_id: str
    integration_mode: IntegrationMode
    execution_mode: str
    engine_command: str
    engine_detect_commands: tuple[str, ...]
    engine_package: str | None
    engine_version: str | None
    acp_command: tuple[str, ...]
    acp_detect_commands: tuple[str, ...]
    acp_package: str | None
    acp_version: str
    install_command: str
    credential_env_names: tuple[str, ...]
    keyless_auth: bool
    # Directories this entry expects under the attempt HOME (engines hard-fail
    # when a configured dir is absent), and host HOME files to copy when the
    # entry authenticates without an API key.
    home_dirs: tuple[str, ...]
    keyless_auth_paths: tuple[str, ...]
    model_binding: ModelBinding
    platforms: tuple[str, ...]
    fixed_env: Mapping[str, str]
    descriptor_digest: str
    # Not part of digest_payload or as_lock_snapshot.
    source: EntrySource = "package"
    # Optional HOME session log. In the digest. Omitted from the lock snapshot.
    usage_journal: UsageJournal | None = None

    def as_lock_snapshot(self) -> dict[str, Any]:
        """Fields safe for lock/evidence (no absolute PATH, no secrets)."""
        return {
            "entry_id": self.entry_id,
            "integration_mode": self.integration_mode,
            "execution_mode": self.execution_mode,
            "engine_command": self.engine_command,
            "engine_package": self.engine_package,
            "engine_version": self.engine_version,
            "acp_command": list(self.acp_command),
            "acp_package": self.acp_package,
            "acp_version": self.acp_version,
            "model_binding": self.model_binding,
            "credential_env_names": list(self.credential_env_names),
            "keyless_auth": self.keyless_auth,
            "descriptor_digest": self.descriptor_digest,
            "platforms": list(self.platforms),
        }

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["acp_command"] = list(self.acp_command)
        d["engine_detect_commands"] = list(self.engine_detect_commands)
        d["acp_detect_commands"] = list(self.acp_detect_commands)
        d["credential_env_names"] = list(self.credential_env_names)
        d["keyless_auth"] = bool(self.keyless_auth)
        d["home_dirs"] = list(self.home_dirs)
        d["keyless_auth_paths"] = list(self.keyless_auth_paths)
        d["platforms"] = list(self.platforms)
        d["fixed_env"] = dict(self.fixed_env)
        return d


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_unpinned_version(version: str) -> bool:
    if any(mark in version for mark in ("^", "~", "*")) or version == "latest":
        return True
    if version.endswith(".x") or ".x." in version or _UNPINNED_VERSION_RE.fullmatch(version):
        return True
    return "x" in re.split(r"[.-]", version)


def _valid_package_name(package: str) -> bool:
    return bool(_SCOPED_PKG_RE.fullmatch(package) or _PKG_NAME_RE.fullmatch(package))


def _split_pkg_token(token: str) -> tuple[str, str] | None:
    if token.startswith("@"):
        body = token[1:]
        if "@" not in body:
            return None
        name, version = body.rsplit("@", 1)
        return "@" + name, version
    if "@" not in token:
        return None
    package, version = token.rsplit("@", 1)
    return package, version


def _command_words(
    raw: Any,
    *,
    location: str,
    allow_flags_after_first: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or not all(isinstance(item, str) and item for item in raw)
    ):
        raise _fail("invalid_schema", "non-empty string list required", location)
    if any(item == "npx" for item in raw):
        raise _fail("acp_install_npx", "npx is not an argv element", location)
    words: list[str] = []
    for index, item in enumerate(raw):
        if index > 0 and allow_flags_after_first and item.startswith("-"):
            if not _FLAG_RE.fullmatch(item):
                raise _fail("invalid_schema", "command flag is not a bare flag", location)
        elif not _CMD_WORD_RE.fullmatch(item):
            raise _fail("invalid_schema", "command word is not a bare name", location)
        words.append(item)
    return tuple(words)


def _relative_home_path(raw: Any, *, location: str) -> str:
    if not isinstance(raw, str) or not raw or raw.startswith(("/", "~")) or "\\" in raw:
        raise _fail("invalid_schema", "path must stay under HOME", location)
    parts = raw.split("/")
    if any(part in {"", ".", ".."} or not _SEGMENT_RE.fullmatch(part) for part in parts):
        raise _fail("invalid_schema", "path must stay under HOME", location)
    return raw


_FIELD_SEGMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_JOURNAL_FIELD_TARGETS = frozenset(
    {"prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd"}
)
_JOURNAL_RECORD_KEYS = frozenset({"type", "usage", "match"})
_JOURNAL_KEYS = frozenset({"dir", "suffix", "records", "fields", "extra"})


def _dotted_field(raw: Any, *, location: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise _fail("invalid_schema", "field path required", location)
    parts = raw.split(".")
    if any(not _FIELD_SEGMENT.fullmatch(part) for part in parts):
        raise _fail("invalid_schema", "field path is not a dotted name", location)
    return raw


def _usage_journal(
    raw: Any,
    *,
    location: str,
    home_dirs: tuple[str, ...],
) -> UsageJournal | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _fail("invalid_schema", "usage_journal must be an object", location)
    unknown = sorted(set(raw) - _JOURNAL_KEYS)
    if unknown:
        raise _fail("invalid_schema", f"unknown key {unknown[0]!r}", location)
    directory = _relative_home_path(raw.get("dir"), location=f"{location}/dir")
    if not any(directory == home or directory.startswith(home + "/") for home in home_dirs):
        raise _fail(
            "invalid_schema",
            "usage_journal dir must sit under home_dirs",
            f"{location}/dir",
        )
    suffix = raw.get("suffix")
    if (
        not isinstance(suffix, str)
        or not suffix.startswith(".")
        or "/" in suffix
        or suffix == "."
        or not _FIELD_SEGMENT.fullmatch(suffix[1:])
    ):
        raise _fail("invalid_schema", "usage_journal suffix must be one extension", location)
    records_raw = raw.get("records")
    if not isinstance(records_raw, list) or not records_raw:
        raise _fail("invalid_schema", "usage_journal records required", f"{location}/records")
    records: list[UsageJournalRecord] = []
    for index, item in enumerate(records_raw):
        rec_loc = f"{location}/records/{index}"
        if not isinstance(item, dict):
            raise _fail("invalid_schema", "usage_journal record must be an object", rec_loc)
        extra_keys = sorted(set(item) - _JOURNAL_RECORD_KEYS)
        if extra_keys:
            raise _fail("invalid_schema", f"unknown key {extra_keys[0]!r}", rec_loc)
        rec_type = item.get("type")
        if not isinstance(rec_type, str) or not _FIELD_SEGMENT.fullmatch(rec_type):
            raise _fail("invalid_schema", "usage_journal record type is invalid", rec_loc)
        usage = _dotted_field(item.get("usage"), location=f"{rec_loc}/usage")
        match_raw = item.get("match", {})
        if not isinstance(match_raw, dict):
            raise _fail("invalid_schema", "usage_journal match must be an object", rec_loc)
        match: list[tuple[str, str]] = []
        for key, value in match_raw.items():
            path = _dotted_field(key, location=f"{rec_loc}/match")
            if not isinstance(value, str):
                raise _fail("invalid_schema", "usage_journal match value must be a string", rec_loc)
            match.append((path, value))
        records.append(UsageJournalRecord(type=rec_type, usage=usage, match=tuple(match)))
    fields = _journal_map(
        raw.get("fields"),
        location=f"{location}/fields",
        allowed=_JOURNAL_FIELD_TARGETS,
        require=True,
    )
    extra = _journal_map(
        raw.get("extra"),
        location=f"{location}/extra",
        allowed=None,
        require=False,
    )
    overlap = set(fields) & set(extra)
    if overlap:
        raise _fail(
            "invalid_schema",
            "usage_journal extra repeats a first-class field",
            f"{location}/extra",
        )
    return UsageJournal(
        dir=directory,
        suffix=suffix,
        records=tuple(records),
        fields=tuple(fields.items()),
        extra=tuple(extra.items()),
    )


def _journal_map(
    raw: Any,
    *,
    location: str,
    allowed: frozenset[str] | None,
    require: bool,
) -> dict[str, str]:
    if raw is None:
        if require:
            raise _fail("invalid_schema", "usage_journal fields required", location)
        return {}
    if not isinstance(raw, dict) or (require and not raw):
        raise _fail("invalid_schema", "usage_journal field map required", location)
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _FIELD_SEGMENT.fullmatch(key):
            raise _fail("invalid_schema", "usage_journal field name is invalid", location)
        if allowed is not None and key not in allowed:
            raise _fail("invalid_schema", "usage_journal field is not first-class usage", location)
        if allowed is None and key in _JOURNAL_FIELD_TARGETS:
            raise _fail(
                "invalid_schema",
                "usage_journal extra repeats a first-class field",
                location,
            )
        out[key] = _dotted_field(value, location=location)
    return out


def _path_list(raw: Any, *, location: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _fail("invalid_schema", "path list required", location)
    return tuple(_relative_home_path(item, location=location) for item in raw)


def _fixed_env(raw: Any, *, location: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _fail("invalid_schema", "fixed_env must be an object", location)
    out: dict[str, str] = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not _ENV_KEY_RE.fullmatch(key)
            or not _ENV_VALUE_RE.fullmatch(value)
            or key in _FIXED_ENV_DENY_EXACT
            or key.startswith("XDG_")
            or key.endswith(_FIXED_ENV_DENY_SUFFIXES)
        ):
            raise _fail("invalid_schema", "fixed_env key or value is not allowed", location)
        out[key] = value
    return out


def _credential_names(raw: Any, *, location: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise _fail("invalid_schema", "credential_env_names must be a list of env names", location)
    names: list[str] = []
    for item in raw:
        if (
            not isinstance(item, str)
            or "=" in item
            or item.startswith("sk-")
            or not _CREDENTIAL_RE.fullmatch(item)
        ):
            raise _fail(
                "invalid_schema",
                "credential_env_names must be env names",
                location,
            )
        names.append(item)
    return tuple(names)


def _pin_pair(
    raw: Mapping[str, Any],
    package_key: str,
    version_key: str,
    *,
    index: int,
) -> tuple[str, str] | None:
    package = raw.get(package_key)
    version = raw.get(version_key)
    if package is None and version is None:
        return None
    loc = f"/entries/{index}/{package_key}"
    if not isinstance(package, str) or not package or not isinstance(version, str) or not version:
        raise _fail("invalid_schema", "package pin must name a package and a version", loc)
    if _is_unpinned_version(version):
        raise _fail(
            "acp_install_unpinned",
            "package version is not pinned",
            f"/entries/{index}/{version_key}",
        )
    if not _valid_package_name(package) or not _VERSION_RE.fullmatch(version):
        raise _fail("invalid_schema", "package pin does not match the install production", loc)
    return package, version


def _install_pairs(command: Any, *, location: str) -> list[tuple[str, str]]:
    if not isinstance(command, str) or not command.startswith(_INSTALL_PREFIX):
        raise _fail(
            "invalid_schema",
            "install_command must be npm install -g <pinned packages>",
            location,
        )
    tokens = command[len(_INSTALL_PREFIX) :].split()
    if not tokens:
        raise _fail("invalid_schema", "install_command must list pinned packages", location)
    if any(token == "npx" for token in tokens):
        raise _fail("acp_install_npx", "npx is not an argv element", location)
    pairs: list[tuple[str, str]] = []
    for token in tokens:
        split = _split_pkg_token(token)
        version = split[1] if split is not None else ""
        if split is None or _is_unpinned_version(version):
            if any(mark in token for mark in ("@latest", "^", "~", "*")) or _is_unpinned_version(
                version
            ):
                raise _fail(
                    "acp_install_unpinned", "install_command version is not pinned", location
                )
            raise _fail("invalid_schema", "install_command must list pinned packages", location)
        package, version = split
        if not _valid_package_name(package) or not _VERSION_RE.fullmatch(version):
            raise _fail("invalid_schema", "install_command must list pinned packages", location)
        pairs.append((package, version))
    return pairs


def canonical_install_command(pairs: set[tuple[str, str]]) -> str:
    """``npm install -g`` with each pin once, sorted by package name."""
    ordered = sorted(pairs, key=lambda item: (item[0], item[1]))
    return _INSTALL_PREFIX + " ".join(f"{package}@{version}" for package, version in ordered)


def pinned_npm_packages(install_command: str) -> str:
    """Package list from an ``install_command`` that matches the production."""
    pairs = _install_pairs(install_command, location="/install_command")
    return " ".join(f"{package}@{version}" for package, version in pairs)


def _parse_entry(
    raw: Mapping[str, Any],
    *,
    index: int,
    source: EntrySource,
) -> AcpEntryDescriptor:
    loc = f"/entries/{index}"
    unknown = sorted(set(raw) - _ENTRY_KEYS)
    if unknown:
        key = unknown[0]
        low = key.lower()
        if low in _SECRET_FIELD_DENYLIST or low.endswith("_secret") or low.endswith("_token"):
            raise _fail(
                "invalid_schema",
                f"secret-bearing field name forbidden: {key}",
                f"{loc}/{key}",
            )
        raise _fail("invalid_schema", f"unknown key {key!r}", f"{loc}/{key}")
    for key in _REQUIRED_ENTRY_KEYS:
        if key not in raw:
            raise _fail("invalid_schema", f"missing required field {key!r}", f"{loc}/{key}")
    entry_id = raw["entry_id"]
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise _fail("invalid_schema", "non-empty string required", f"{loc}/entry_id")
    mode = raw["integration_mode"]
    if type(mode) is not int or mode not in (1, 2, 3):
        raise _fail(
            "invalid_schema", "integration_mode must be 1, 2, or 3", f"{loc}/integration_mode"
        )
    if raw["execution_mode"] != "acp-stdio":
        raise _fail("invalid_schema", "execution_mode must be acp-stdio", f"{loc}/execution_mode")
    engine_detect = _command_words(
        raw["engine_detect_commands"],
        location=f"{loc}/engine_detect_commands",
        allow_flags_after_first=False,
    )
    acp_detect = _command_words(
        raw["acp_detect_commands"],
        location=f"{loc}/acp_detect_commands",
        allow_flags_after_first=False,
    )
    acp_command = _command_words(
        raw["acp_command"],
        location=f"{loc}/acp_command",
        allow_flags_after_first=True,
    )
    engine_command_raw = raw.get("engine_command")
    if engine_command_raw is None:
        engine_command = engine_detect[0]
    elif isinstance(engine_command_raw, str) and _CMD_WORD_RE.fullmatch(engine_command_raw):
        engine_command = engine_command_raw
    else:
        raise _fail("invalid_schema", "engine_command is not a bare name", f"{loc}/engine_command")
    if raw["model_binding"] not in ("config-option", "entry-default-only"):
        raise _fail("invalid_schema", "model_binding is invalid", f"{loc}/model_binding")
    platforms_raw = raw["platforms"]
    if (
        not isinstance(platforms_raw, list)
        or not platforms_raw
        or not all(item in ("darwin", "linux") for item in platforms_raw)
    ):
        raise _fail("invalid_schema", "platforms must list darwin or linux", f"{loc}/platforms")
    keyless_raw = raw.get("keyless_auth", False)
    if not isinstance(keyless_raw, bool):
        raise _fail("invalid_schema", "keyless_auth must be a boolean", f"{loc}/keyless_auth")
    fixed_env = _fixed_env(raw.get("fixed_env"), location=f"{loc}/fixed_env")
    credential_env_names = _credential_names(
        raw["credential_env_names"],
        location=f"{loc}/credential_env_names",
    )
    home_dirs = _path_list(raw.get("home_dirs"), location=f"{loc}/home_dirs")
    usage_journal = _usage_journal(
        raw.get("usage_journal"),
        location=f"{loc}/usage_journal",
        home_dirs=home_dirs,
    )
    keyless_auth_paths = _path_list(
        raw.get("keyless_auth_paths"),
        location=f"{loc}/keyless_auth_paths",
    )
    for rel in keyless_auth_paths:
        if not any(rel == home or rel.startswith(home + "/") for home in home_dirs):
            raise _fail(
                "invalid_schema",
                "keyless_auth_paths must sit under home_dirs",
                f"{loc}/keyless_auth_paths",
            )
        if source == "user" and rel.split("/", 1)[0] in _USER_AUTH_ROOTS:
            raise _fail(
                "invalid_schema",
                "keyless_auth_paths must not start at a credential directory",
                f"{loc}/keyless_auth_paths",
            )
    engine_pin = _pin_pair(raw, "engine_package", "engine_version", index=index)
    acp_pin = _pin_pair(raw, "acp_package", "acp_version", index=index)
    pins = {pin for pin in (engine_pin, acp_pin) if pin is not None}
    if not pins:
        raise _fail("invalid_schema", "at least one package pin is required", f"{loc}/acp_package")
    declared = _install_pairs(raw["install_command"], location=f"{loc}/install_command")
    if set(declared) != pins:
        raise _fail(
            "invalid_schema",
            "install_command tokens must equal the pinned packages",
            f"{loc}/install_command",
        )
    install_command = canonical_install_command(pins)
    digest_payload = {
        "entry_id": entry_id,
        "integration_mode": mode,
        "execution_mode": raw["execution_mode"],
        "engine_command": raw.get("engine_command"),
        "engine_detect_commands": list(engine_detect),
        "engine_package": raw.get("engine_package"),
        "engine_version": raw.get("engine_version"),
        "acp_command": list(acp_command),
        "acp_detect_commands": list(acp_detect),
        "acp_package": raw.get("acp_package"),
        "acp_version": raw["acp_version"],
        "model_binding": raw["model_binding"],
        "credential_env_names": list(credential_env_names),
        "keyless_auth": keyless_raw,
        "home_dirs": list(home_dirs),
        "keyless_auth_paths": list(keyless_auth_paths),
        "platforms": list(platforms_raw),
        "fixed_env": fixed_env,
    }
    if usage_journal is not None:
        digest_payload["usage_journal"] = usage_journal.digest_payload()
    return AcpEntryDescriptor(
        entry_id=entry_id,
        integration_mode=mode,
        execution_mode=str(raw["execution_mode"]),
        engine_command=engine_command,
        engine_detect_commands=engine_detect,
        engine_package=engine_pin[0] if engine_pin else None,
        engine_version=engine_pin[1] if engine_pin else None,
        acp_command=acp_command,
        acp_detect_commands=acp_detect,
        acp_package=acp_pin[0] if acp_pin else None,
        acp_version=str(raw["acp_version"]),
        install_command=install_command,
        credential_env_names=credential_env_names,
        keyless_auth=keyless_raw,
        home_dirs=home_dirs,
        keyless_auth_paths=keyless_auth_paths,
        model_binding=raw["model_binding"],
        platforms=tuple(platforms_raw),
        fixed_env=fixed_env,
        descriptor_digest=_canonical_digest(digest_payload),
        source=source,
        usage_journal=usage_journal,
    )


def _parse_rows(
    entries: list[Any],
    *,
    source: EntrySource,
    packaged_ids: set[str] | None,
) -> dict[str, AcpEntryDescriptor]:
    out: dict[str, AcpEntryDescriptor] = {}
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise _fail("invalid_schema", "entry must be an object", f"/entries/{index}")
        desc = _parse_entry(raw, index=index, source=source)
        if packaged_ids is not None and desc.entry_id in packaged_ids:
            raise _fail(
                "acp_entry_id_collision",
                "entry_id collides with a packaged entry",
                f"/entries/{index}/entry_id",
            )
        if desc.entry_id in out:
            raise _fail(
                "acp_entry_duplicate",
                f"duplicate entry_id: {desc.entry_id}",
                f"/entries/{index}/entry_id",
            )
        out[desc.entry_id] = desc
    return out


def _table_from_document(
    doc: Any, *, source: EntrySource, allow_empty: bool
) -> dict[str, AcpEntryDescriptor]:
    if not isinstance(doc, dict) or "entries" not in doc:
        raise _fail("invalid_schema", "top-level object with entries required", "/")
    entries = doc["entries"]
    if not isinstance(entries, list) or (not entries and not allow_empty):
        raise _fail("invalid_schema", "entries must be a non-empty list", "/entries")
    return _parse_rows(entries, source=source, packaged_ids=None)


def _read_json_object(path: Path, *, location: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("invalid_schema", "acp entries file is not json", location) from exc


def load_registry_document(path: Path | None = None) -> dict[str, Any]:
    """Packaged registry document. Does not read or merge the home file."""
    if path is not None:
        doc = _read_json_object(path, location=path.name)
    else:
        try:
            ref = resources.files("ageval.plugins.contrib.acp").joinpath(_REGISTRY_RESOURCE)
            with ref.open("r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
            doc = _read_json_object(
                Path(__file__).with_name(_REGISTRY_RESOURCE), location=_REGISTRY_RESOURCE
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _fail(
                "invalid_schema", "packaged acp entries are not json", _REGISTRY_RESOURCE
            ) from exc
    if not isinstance(doc, dict):
        raise _fail("invalid_schema", "top-level object with entries required", "/")
    return doc


def _unreadable_home() -> AcpRegistryError:
    return _fail(
        "acp_user_entries_unreadable",
        "could not read acp-entries.json",
        _HOME_FILENAME,
    )


def _read_home_rows(packaged_ids: set[str]) -> dict[str, AcpEntryDescriptor] | None:
    home = ageval_home()
    path = home / _HOME_FILENAME
    if path.is_symlink():
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise _unreadable_home() from exc
        if not resolved.is_relative_to(home) or not resolved.is_file():
            raise _unreadable_home()
        target = resolved
    elif not path.exists():
        return None
    elif not path.is_file():
        raise _unreadable_home()
    else:
        target = path
    try:
        if target.stat().st_size > _MAX_HOME_BYTES:
            raise _unreadable_home()
        text = target.read_text(encoding="utf-8")
    except AcpRegistryError:
        raise
    except (OSError, UnicodeError) as exc:
        raise _unreadable_home() from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _unreadable_home() from exc
    if not isinstance(doc, dict):
        raise _fail("invalid_schema", "home entry file must be an object", "/")
    unknown = sorted(set(doc) - {"schema_version", "entries"})
    if unknown:
        key = unknown[0]
        raise _fail("invalid_schema", f"unknown key {key!r}", f"/{key}")
    version = doc.get("schema_version")
    if type(version) is not int or version != 1:
        raise _fail("invalid_schema", "schema_version must be integer 1", "/schema_version")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise _fail("invalid_schema", "entries must be a list", "/entries")
    if len(entries) > _MAX_HOME_ENTRIES:
        raise _fail("invalid_schema", "at most 32 entries", "/entries")
    return _parse_rows(entries, source="user", packaged_ids=packaged_ids)


def load_acp_entries(path: str | None = None) -> dict[str, AcpEntryDescriptor]:
    """Merged table when ``path`` is omitted. An explicit path is that file only."""
    if path in _CACHE:
        return _CACHE[path]
    if path is not None:
        table = _table_from_document(
            load_registry_document(Path(path)), source="package", allow_empty=False
        )
        _CACHE[path] = table
        return table
    packaged = _table_from_document(
        load_registry_document(None), source="package", allow_empty=False
    )
    home_rows = _read_home_rows(set(packaged))
    merged = dict(packaged)
    if home_rows:
        merged.update(home_rows)
    _CACHE[None] = merged
    return merged


def peek_acp_entries() -> dict[str, AcpEntryDescriptor] | None:
    """Merged table already loaded with ``path=None``. Empty cache is ``None``."""
    if None not in _CACHE:
        return None
    return _CACHE[None]


def get_entry(entry_id: str, *, path: str | None = None) -> AcpEntryDescriptor | None:
    return load_acp_entries(path).get(entry_id)


def list_entry_ids(*, path: str | None = None) -> list[str]:
    return sorted(load_acp_entries(path))


def current_platform_token() -> str:
    return platform.system().lower()


def readiness_for(
    desc: AcpEntryDescriptor,
    *,
    which: Any | None = None,
    platform_token: str | None = None,
) -> dict[str, Any]:
    """Compute inventory readiness without starting models or reading secrets."""
    plat = platform_token or current_platform_token()
    # Map common aliases
    plat_norm = {"macos": "darwin", "osx": "darwin"}.get(plat, plat)
    supported = plat_norm in {p.lower() for p in desc.platforms} or any(
        p.lower() in {plat_norm, "any", "*"} for p in desc.platforms
    )
    if not supported:
        return {
            "entry_id": desc.entry_id,
            "engine_ready": False,
            "acp_entry_ready": False,
            "readiness": "unsupported-platform",
            "engine_binary": None,
            "engine_path": None,
            "acp_binary": None,
            "acp_path": None,
        }

    eng_name, eng_path = probe_commands(desc.engine_detect_commands, which=which)
    acp_name, acp_path = probe_commands(desc.acp_detect_commands, which=which)
    engine_ready = eng_path is not None
    acp_ready = acp_path is not None

    readiness: Readiness
    if desc.integration_mode == 1:
        if engine_ready and acp_ready:
            readiness = "ready"
        elif engine_ready and not acp_ready:
            readiness = "adapter-missing"
        elif not engine_ready and acp_ready:
            readiness = "engine-missing"
        else:
            readiness = "engine-missing"
    else:
        # Mode 2/3: single entry command family.
        readiness = "ready" if acp_ready else "entry-missing"
        # engine_ready tracks optional detect for Mode 3.
        if desc.integration_mode == 2:
            engine_ready = acp_ready

    return {
        "entry_id": desc.entry_id,
        "engine_ready": engine_ready,
        "acp_entry_ready": acp_ready,
        "readiness": readiness,
        "engine_binary": eng_name
        if eng_path
        else (desc.engine_detect_commands[0] if desc.engine_detect_commands else None),
        "engine_path": eng_path,
        "acp_binary": acp_name if acp_path else (desc.acp_command[0] if desc.acp_command else None),
        "acp_path": acp_path,
    }


def clear_registry_cache() -> None:
    _CACHE.clear()
