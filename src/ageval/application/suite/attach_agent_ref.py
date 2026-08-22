"""Inject a published ``agent_ref`` onto matching overlay roles (design/12, /14).

Compare uses ``_binding_role_key`` (executor, ACP entry, model, secret-free
plugin options). The write is provenance only: it must not change fingerprint
identity, lock bytes, or PASS.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ageval.agents.refs import published_agent_ref_parts
from ageval.application.suite.suite_config_fingerprint import _binding_role_key
from ageval.config.errors import ERROR_INVALID_SCHEMA, ConfigError

_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_DIGEST_SHORT_HEX = 12


class AttachAgentRefError(ConfigError):
    """Fail-closed overlay attach. Same operator shape as other Config errors."""


@dataclass(frozen=True, slots=True)
class AttachAgentResult:
    overlay: dict[str, Any]
    roles: tuple[str, ...]
    changed: bool
    agent_ref: str
    package_id: str
    version: str


def short_package_digest(digest: str) -> str:
    text = digest.strip()
    if text.startswith("sha256:"):
        return "sha256:" + text[len("sha256:") :][:_DIGEST_SHORT_HEX]
    return text[:_DIGEST_SHORT_HEX]


def format_published_agent_ref(package_id: str, version: str, digest: str = "") -> str:
    ref = f"{package_id.strip()}@{version.strip()}"
    if digest.strip():
        ref = f"{ref}+{short_package_digest(digest)}"
    return ref


def parse_published_agent_spec(spec: str) -> tuple[str | None, str, str]:
    """Split ``[role=]org/name@version`` into ``(role, package_id, version)``.

    ``local/`` and ``file:`` refs fail closed — they cannot create Hub provenance.
    """
    text = spec.strip()
    if not text:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "agent ref must not be empty",
            location="/agent",
        )
    role: str | None = None
    left, sep, rest = text.partition("=")
    if sep and _ROLE_RE.fullmatch(left.strip()) and rest.strip():
        role = left.strip()
        text = rest.strip()
    if "@" not in text:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "agent ref must be org/name@version",
            location=spec,
        )
    parts = published_agent_ref_parts(text)
    if parts is None:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "agent ref must be a published org/name@version (not local/ or file:)",
            location=spec,
        )
    return role, parts[0], parts[1]


def inject_published_agent_ref(
    overlay: Mapping[str, Any] | None,
    *,
    published_binding: Mapping[str, Any],
    agent_ref: str,
    role: str | None = None,
) -> AttachAgentResult:
    """Copy *overlay* and set ``agent_ref`` on every role whose binding matches.

    *role* limits the write to one overlay role. Fail closed when nothing
    matches, a named role is missing, or a matching role already points at a
    different published ref. Same ref is idempotent.
    """
    parts = published_agent_ref_parts(agent_ref)
    if parts is None:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "agent ref must be a published org/name@version (not local/ or file:)",
            location="/agent_ref",
        )
    package_id, version = parts
    if not isinstance(published_binding, Mapping) or not published_binding:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "published agent binding is missing",
            location="/binding",
        )
    if not isinstance(overlay, Mapping):
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "suite job_overlay is missing",
            location="/job_overlay",
        )
    profiles = overlay.get("agent_profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "suite job_overlay has no agent_profiles",
            location="/job_overlay/agent_profiles",
        )

    want_key = _binding_role_key(published_binding)
    want_role = role.strip() if isinstance(role, str) and role.strip() else None
    if want_role is not None and want_role not in profiles:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            f"overlay role {want_role!r} is missing",
            location=f"/job_overlay/agent_profiles/{want_role}",
        )

    new_profiles: dict[str, Any] = {}
    attached: list[str] = []
    changed = False
    for role_id, raw in profiles.items():
        rid = str(role_id)
        if not isinstance(raw, Mapping):
            new_profiles[rid] = raw
            continue
        row = dict(raw)
        if want_role is not None and rid != want_role:
            new_profiles[rid] = row
            continue
        if _binding_role_key(row) != want_key:
            if want_role is not None:
                raise AttachAgentRefError(
                    ERROR_INVALID_SCHEMA,
                    "overlay binding does not match the published agent",
                    location=f"/job_overlay/agent_profiles/{rid}",
                )
            new_profiles[rid] = row
            continue
        existing = row.get("agent_ref")
        if isinstance(existing, str) and existing.strip() and existing.strip() != agent_ref:
            existing_parts = published_agent_ref_parts(existing)
            if existing_parts != (package_id, version):
                raise AttachAgentRefError(
                    ERROR_INVALID_SCHEMA,
                    "overlay role already has a different agent_ref",
                    location=f"/job_overlay/agent_profiles/{rid}/agent_ref",
                )
            row["agent_ref"] = agent_ref
            changed = True
        elif not (isinstance(existing, str) and existing.strip()):
            row["agent_ref"] = agent_ref
            changed = True
        attached.append(rid)
        new_profiles[rid] = row

    if not attached:
        raise AttachAgentRefError(
            ERROR_INVALID_SCHEMA,
            "no overlay role matches the published agent binding",
            location="/job_overlay/agent_profiles",
        )

    new_overlay = {**dict(overlay), "agent_profiles": new_profiles}
    return AttachAgentResult(
        overlay=new_overlay,
        roles=tuple(attached),
        changed=changed,
        agent_ref=agent_ref,
        package_id=package_id,
        version=version,
    )
