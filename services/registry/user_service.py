"""Public user identity for Hub. Official is Registry-computed."""

from __future__ import annotations

from typing import Any

from services.registry.errors import RegistryAppError
from services.registry.maintainers import is_maintainer
from services.registry.official import is_official_upload_org
from services.registry.org_service import normalize_description
from services.registry.store import TokenInfo, _normalize_user_id, org_to_dict

_USER_DESCRIPTION_MAX = 280


class UserService:
    def __init__(self, orgs: Any) -> None:
        self.orgs = orgs

    def get_public(self, user_id: str) -> dict[str, Any]:
        uid = _normalize_user_id(user_id)
        if not uid:
            raise RegistryAppError("invalid_request", "user_id required", http_status=400)
        profile = self.orgs.get_user_profile(uid)
        memberships = self.orgs.list_orgs_for_user(uid)
        if profile is None and not memberships:
            raise RegistryAppError("not_found", "user not found", http_status=404)
        official_orgs: list[dict[str, Any]] = []
        for org, _role in memberships:
            if not is_official_upload_org(org.org_id):
                continue
            row = org_to_dict(org)
            official_orgs.append(
                {
                    "org_id": row["org_id"],
                    "display_name": row["display_name"],
                    "official": True,
                }
            )
        return {
            "user_id": uid,
            "display_name": profile.display_name if profile else "",
            "avatar_url": profile.avatar_url if profile else "",
            "description": profile.description if profile else "",
            "official": bool(official_orgs),
            "official_orgs": official_orgs,
            "maintainer": is_maintainer(uid),
        }

    def patch(
        self,
        *,
        user_id: str,
        description: object,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        uid = _normalize_user_id(user_id)
        if not uid:
            raise RegistryAppError("invalid_request", "user_id required", http_status=400)
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        if _normalize_user_id(auth.user_id) != uid:
            raise RegistryAppError("forbidden", "cannot edit another user", http_status=403)
        text = normalize_description(description, max_len=_USER_DESCRIPTION_MAX)
        self.orgs.set_user_description(uid, text)
        return self.get_public(uid)
