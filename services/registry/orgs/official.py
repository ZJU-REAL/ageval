"""Hub marketplace official-org policy. Not a lock/run gate."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from services.registry.dataset import is_draft_version

DEFAULT_OFFICIAL_ORGS: tuple[str, ...] = ("official",)
ENV_OFFICIAL_ORGS = "AGEVAL_OFFICIAL_ORGS"


def official_orgs() -> frozenset[str]:
    raw = os.environ.get(ENV_OFFICIAL_ORGS, "").strip()
    if raw:
        return frozenset(part.strip() for part in raw.split(",") if part.strip())
    return frozenset(DEFAULT_OFFICIAL_ORGS)


def is_official_upload_org(org_id: str | None) -> bool:
    if not org_id:
        return False
    allowed = {item.casefold() for item in official_orgs()}
    return org_id.casefold() in allowed


def official_dataset_ids(releases: Iterable[Any]) -> frozenset[str]:
    """Dataset ids that have a non-draft official-org dataset release."""
    from services.registry.store import package_kind_for_media_type

    out: set[str] = set()
    for row in releases:
        dataset_id = str(row.dataset_id or "").strip()
        if not dataset_id or is_draft_version(row.version):
            continue
        try:
            if package_kind_for_media_type(str(row.media_type or "")) != "dataset":
                continue
        except ValueError:
            continue
        if is_official_upload_org(row.org_id):
            out.add(dataset_id)
    return frozenset(out)


def is_official_dataset(dataset_id: str, releases: Iterable[Any]) -> bool:
    """True iff any non-draft dataset release for *dataset_id* is official-org."""
    want = (dataset_id or "").strip()
    if not want:
        return False
    return want in official_dataset_ids(releases)
