"""Project ``--agent`` specs into a ``ageval.profiles/1`` document (design/14).

Spec forms (repeatable):

* ``<ref>``            — bind ALL role slots (wildcard ``"*"`` binding)
* ``<role>=<ref>``     — bind one role; exact role wins over wildcard
* ``<path>``           — local dir or ``agent.yaml`` (dev loop; ref = ``file:…@dev``)

``<ref>`` is a short builtin id (``pi``), a pinned local-cache id
``local/<id>@<version>``, or ``org/name@<version>`` (short ``<id>@<version>``
falls back to ``local/<id>``).
The synthesized document enters the existing ``profiles_path`` lane, so lock /
job_overlay / fingerprint behave exactly as with a hand-written profiles file.
``agent_ref`` (``<id>@<version>+sha256:<digest12>``) is injected per binding as
provenance; it never enters suite fingerprint identity. Optional ``model``
patches ``binding.model`` on every role this ``--agent`` bound (package default
otherwise).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ageval.agents.manifest import AgentManifest, load_agent_manifest
from ageval.agents.paths import agents_root
from ageval.agents.store import LOCAL_NAMESPACE, resolve_installed_ref
from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError
from ageval.config.profiles import (
    PROFILES_FORMAT,
    WILDCARD_ROLE,
    parse_job_mapping,
    write_profiles_yaml,
)
from ageval.plugins.store import compute_tree_digest

_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_DIGEST_SHORT_HEX = 12

PROJECTIONS_DIRNAME = ".projections"


def _short_digest(digest: str) -> str:
    if digest.startswith("sha256:"):
        return "sha256:" + digest[len("sha256:") :][:_DIGEST_SHORT_HEX]
    return digest[:_DIGEST_SHORT_HEX]


def _looks_like_path(ref: str) -> bool:
    if ref.startswith(("./", "../", "/", "~")):
        return True
    return Path(ref).exists()


def _load_from_path(ref: str) -> tuple[AgentManifest, str]:
    path = Path(ref).expanduser().resolve(strict=False)
    manifest = load_agent_manifest(path)
    if manifest.root is not None:
        digest = compute_tree_digest(manifest.root)
    else:
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest, f"file:{path}@dev+{_short_digest(digest)}"


def _load_from_builtin(ref: str) -> tuple[AgentManifest, str] | None:
    from ageval.agents.reserved import builtin_harness_root, canonical_harness_id

    hit = canonical_harness_id(ref)
    if hit is None:
        return None
    root = builtin_harness_root(hit)
    manifest = load_agent_manifest(root)
    digest = compute_tree_digest(root)
    return manifest, f"{hit}@{manifest.version}+{_short_digest(digest)}"


def _load_ref(ref: str) -> tuple[AgentManifest, str]:
    if _looks_like_path(ref):
        return _load_from_path(ref)
    if "@" not in ref and "/" not in ref:
        loaded = _load_from_builtin(ref)
        if loaded is not None:
            return loaded
    return _load_from_cache(ref)


def _load_from_cache(ref: str) -> tuple[AgentManifest, str]:
    agent_id, _, version = ref.rpartition("@")
    if not agent_id or not version:
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "--agent ref must be <id>@<version> or a local path "
            "(install first: ageval agent install …)",
            location=ref,
        )
    if version.startswith("sha256:"):
        raise ConfigError(
            ERROR_INVALID_SCHEMA,
            "--agent by digest requires registry install; pin @<version> locally",
            location=ref,
        )
    try:
        entry, root = resolve_installed_ref(agent_id, version)
    except ConfigError:
        if "/" in agent_id:
            raise
        entry, root = resolve_installed_ref(f"{LOCAL_NAMESPACE}/{agent_id}", version)
    manifest = load_agent_manifest(root)
    return manifest, f"{entry.agent_id}@{entry.version}+{_short_digest(entry.digest)}"


def parse_agent_spec(raw: str) -> tuple[str, str]:
    """Split one --agent value into ``(role_or_wildcard, ref)``."""
    spec = raw.strip()
    if not spec:
        raise ConfigError(ERROR_INVALID_SCHEMA, "--agent must not be empty", location=raw)
    role, sep, rest = spec.partition("=")
    if sep and _ROLE_RE.fullmatch(role.strip()) and rest.strip():
        return role.strip(), rest.strip()
    return WILDCARD_ROLE, spec


def bindings_from_agent_specs(specs: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve specs into a profiles bindings map with ``agent_ref`` injected."""
    bindings: dict[str, dict[str, Any]] = {}
    for raw in specs:
        role, ref = parse_agent_spec(raw)
        if role in bindings:
            raise ConfigError(
                ERROR_INVALID_SCHEMA,
                f"duplicate --agent for role {role!r}",
                location=raw,
            )
        manifest, agent_ref = _load_ref(ref)
        binding = copy.deepcopy(manifest.binding)
        binding["agent_ref"] = agent_ref
        bindings[role] = binding
    return bindings


def resolve_agent_specs(specs: list[str], model: str | None = None) -> Path:
    """Synthesize a ``ageval.profiles/1`` file for the profiles lane; return its path.

    Written content-addressed under ``$AGEVAL_HOME/agents/.projections`` so the
    exact document a run used stays inspectable and re-runnable (also works
    when the Dataset itself is a registry ref with no local root).
    ``model`` (from ``--model``) overrides ``binding.model`` on bound roles.
    """
    bindings = bindings_from_agent_specs(specs)
    if model:
        for binding in bindings.values():
            current = binding.get("model")
            if isinstance(current, Mapping):
                updated = dict(current)
                updated["id"] = model
                binding["model"] = updated
            else:
                binding["model"] = {"id": model}
    document = {"format": PROFILES_FORMAT, "agent_profiles": bindings}
    # Re-parse for shape safety before anything reads the file.
    parse_job_mapping(document, location="--agent")
    canon = json.dumps(document, sort_keys=True, separators=(",", ":"))
    name = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
    out = agents_root() / PROJECTIONS_DIRNAME / f"{name}.yaml"
    write_profiles_yaml(out, document)
    return out
