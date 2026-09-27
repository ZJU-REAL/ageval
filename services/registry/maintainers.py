"""Platform maintainers: builtin plugin/agent owners. Not official-org."""

from __future__ import annotations

import os

from services.registry.auth.tokens import (
    TokenInfo,
    _normalize_user_id,
)

ENV_MAINTAINERS = "AGEVAL_REGISTRY_MAINTAINERS"
MAINTAINER_INBOX_ORG = "_maintainers"

COLLECT_OFF = "off"
COLLECT_OFFICIAL = "official"
COLLECT_OFFICIAL_AND_PERSONAL = "official_and_personal"
COLLECT_MODES = frozenset({COLLECT_OFF, COLLECT_OFFICIAL, COLLECT_OFFICIAL_AND_PERSONAL})
DEFAULT_BUILTIN_COLLECT = COLLECT_OFFICIAL


def maintainer_logins() -> frozenset[str]:
    raw = os.environ.get(ENV_MAINTAINERS, "").strip()
    if not raw:
        return frozenset()
    out: set[str] = set()
    for part in raw.split(","):
        uid = _normalize_user_id(part)
        if uid:
            out.add(uid)
    return frozenset(out)


def is_maintainer(user_id: str | None) -> bool:
    uid = _normalize_user_id(user_id)
    return bool(uid) and uid in maintainer_logins()


def auth_is_maintainer(auth: TokenInfo) -> bool:
    return is_maintainer(auth.user_id)
