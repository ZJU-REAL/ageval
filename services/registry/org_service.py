"""Org / members / invites."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from services.registry.access import AccessPolicy
from services.registry.brand_marks import normalize_icon_github, normalize_icon_key
from services.registry.errors import RegistryAppError
from services.registry.official import is_official_upload_org
from services.registry.store import (
    TokenInfo,
    _normalize_user_id,
    invite_key_to_dict,
    membership_to_dict,
    now,
    org_to_dict,
)

_ORG_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
_DISPLAY_NAME_MAX = 80
_DESCRIPTION_MAX = 500


def _normalize_display_name(raw: object) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError("invalid_request", "display_name must be a string", http_status=400)
    name = " ".join(raw.split())
    if any(ord(ch) < 32 for ch in name):
        raise RegistryAppError(
            "invalid_request",
            "display_name cannot include control characters",
            http_status=400,
        )
    if len(name) > _DISPLAY_NAME_MAX:
        raise RegistryAppError(
            "invalid_request",
            f"display_name must be at most {_DISPLAY_NAME_MAX} characters",
            http_status=400,
        )
    return name


def normalize_description(raw: object, *, max_len: int) -> str:
    if not isinstance(raw, str):
        raise RegistryAppError(
            "invalid_request",
            "description must be a string",
            http_status=400,
        )
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if any(ord(ch) < 32 and ch != "\n" for ch in text):
        raise RegistryAppError(
            "invalid_request",
            "description cannot include control characters",
            http_status=400,
        )
    if len(text) > max_len:
        raise RegistryAppError(
            "invalid_request",
            f"description must be at most {max_len} characters",
            http_status=400,
        )
    return text


class OrgService:
    def __init__(self, orgs: Any, access: AccessPolicy) -> None:
        self.orgs = orgs
        self.access = access

    def get(self, org_id: str) -> Any:
        return self.orgs.get_org(org_id)

    def owner_status(self, org_id: str, auth: TokenInfo) -> str:
        return self.access.org_owner_status(org_id=org_id, auth=auth)

    def create(
        self,
        *,
        name: str,
        display_name: str,
        is_claimable: bool,
        auth: TokenInfo,
        description: object = "",
    ) -> dict[str, Any]:
        if not auth.scopes:
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "user identity required", http_status=401)
        name = name.strip().casefold()
        display_name = display_name or name
        desc = normalize_description(description, max_len=_DESCRIPTION_MAX)
        if not name or not _ORG_NAME_RE.match(name):
            raise RegistryAppError(
                "invalid_request",
                "name must be lowercase slug [a-z0-9][a-z0-9_-]*",
                http_status=400,
            )
        if is_official_upload_org(name) and not AccessPolicy.is_admin(auth.scopes):
            raise RegistryAppError(
                "forbidden",
                "official org is reserved; admin required",
                http_status=403,
            )
        if is_official_upload_org(name):
            is_claimable = False
        try:
            org = self.orgs.create_org(
                name=name,
                owner_user_id=auth.user_id,
                display_name=display_name,
                description=desc,
                is_claimable=is_claimable,
            )
        except ValueError as exc:
            raise RegistryAppError("conflict", "org already exists", http_status=409) from exc
        return org_to_dict(org)

    def list_for_user(self, *, auth: TokenInfo) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        items = []
        for org, role in self.orgs.list_orgs_for_user(auth.user_id):
            d = org_to_dict(org)
            d["role"] = role
            items.append(d)
        return {"items": items}

    def patch(
        self,
        *,
        org_id: str,
        auth: TokenInfo,
        display_name: object = None,
        description: object = None,
        icon_key: object = None,
        icon_github: object = None,
    ) -> dict[str, Any]:
        org_id = org_id.casefold()
        self._require_owner(org_id, auth)
        has_icon_key = icon_key is not None
        has_icon_github = icon_github is not None
        if (
            display_name is None
            and description is None
            and not has_icon_key
            and not has_icon_github
        ):
            raise RegistryAppError(
                "invalid_request",
                "display_name or description or icon required",
                http_status=400,
            )
        name = None if display_name is None else _normalize_display_name(display_name)
        desc = (
            None
            if description is None
            else normalize_description(description, max_len=_DESCRIPTION_MAX)
        )
        next_key: str | None = None
        next_github: str | None = None
        if has_icon_key or has_icon_github:
            current = self.orgs.get_org(org_id)
            if current is None:
                raise RegistryAppError("not_found", "org not found", http_status=404)
            key = normalize_icon_key(icon_key) if has_icon_key else current.icon_key
            github = normalize_icon_github(icon_github) if has_icon_github else current.icon_github
            next_key = key or ""
            next_github = github or ""
        try:
            org = self.orgs.update_org(
                org_id,
                display_name=name,
                description=desc,
                icon_key=next_key,
                icon_github=next_github,
            )
        except LookupError as exc:
            raise RegistryAppError("not_found", "org not found", http_status=404) from exc
        payload = org_to_dict(org)
        if auth.user_id:
            mem = self.orgs.membership(org.org_id, auth.user_id)
            if mem:
                payload["role"] = mem.role
        return payload

    def get_public(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        org = self.orgs.get_org(org_id.casefold())
        if org is None:
            raise RegistryAppError("not_found", "org not found", http_status=404)
        payload = org_to_dict(org)
        if auth.user_id:
            m = self.orgs.membership(org.org_id, auth.user_id)
            if m:
                payload["role"] = m.role
        return payload

    def claim(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "user identity required", http_status=401)
        org_id = org_id.casefold()
        if is_official_upload_org(org_id):
            raise RegistryAppError(
                "forbidden",
                "official org is reserved; cannot claim",
                http_status=403,
            )
        try:
            org = self.orgs.claim_org(org_id, auth.user_id)
        except LookupError as exc:
            raise RegistryAppError("not_found", "org not found", http_status=404) from exc
        except PermissionError as exc:
            raise RegistryAppError("forbidden", str(exc), http_status=403) from exc
        return org_to_dict(org)

    def create_invite(
        self,
        *,
        org_id: str,
        max_uses: object,
        expires_at: object,
        expires_in_days: object,
        auth: TokenInfo,
    ) -> dict[str, Any]:
        org_id = org_id.casefold()
        self._require_owner(org_id, auth)
        uses: int | None = None
        if max_uses is not None and max_uses != "":
            try:
                uses = int(max_uses)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise RegistryAppError(
                    "invalid_request", "max_uses must be int", http_status=400
                ) from exc
        exp: float | None = None
        if expires_at is not None and expires_at != "":
            try:
                exp = float(expires_at)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise RegistryAppError(
                    "invalid_request",
                    "expires_at must be unix timestamp",
                    http_status=400,
                ) from exc
        if exp is not None and exp <= now():
            raise RegistryAppError(
                "invalid_request",
                "expires_at must be in the future",
                http_status=400,
            )
        if exp is None and expires_in_days is not None:
            try:
                days = float(expires_in_days)  # type: ignore[arg-type]
                if days <= 0:
                    raise ValueError("non-positive")
                exp = now() + days * 86400.0
            except (TypeError, ValueError) as exc:
                raise RegistryAppError(
                    "invalid_request",
                    "expires_in_days must be positive number",
                    http_status=400,
                ) from exc
        plain = f"ageval-inv_{secrets.token_urlsafe(24)}"
        token_hash = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        prefix = plain[:16] + "…"
        try:
            row = self.orgs.create_invite_key(
                org_id=org_id,
                created_by=auth.user_id or "",
                token_hash=token_hash,
                token_prefix=prefix,
                max_uses=uses,
                expires_at=exp,
            )
        except LookupError as exc:
            raise RegistryAppError("not_found", "org not found", http_status=404) from exc
        except ValueError as exc:
            raise RegistryAppError("invalid_request", str(exc), http_status=400) from exc
        return invite_key_to_dict(row, invite_key=plain)

    def list_invites(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        self._require_owner(org_id, auth)
        items = [invite_key_to_dict(r) for r in self.orgs.list_invite_keys(org_id)]
        return {"org_id": org_id, "items": items}

    def revoke_invite(self, *, org_id: str, key_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        self._require_owner(org_id, auth)
        try:
            row = self.orgs.revoke_invite_key(org_id, key_id)
        except LookupError as exc:
            raise RegistryAppError("not_found", "invite key not found", http_status=404) from exc
        return invite_key_to_dict(row)

    def join(self, *, invite_key: str, auth: TokenInfo) -> dict[str, Any]:
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "user identity required", http_status=401)
        invite = invite_key.strip()
        if not invite:
            raise RegistryAppError("invalid_request", "invite_key required", http_status=400)
        token_hash = hashlib.sha256(invite.encode("utf-8")).hexdigest()
        try:
            org, mem = self.orgs.redeem_invite_key(token_hash=token_hash, user_id=auth.user_id)
        except LookupError as exc:
            raise RegistryAppError("not_found", "invalid invite key", http_status=404) from exc
        except PermissionError as exc:
            raise RegistryAppError("forbidden", str(exc), http_status=403) from exc
        except ValueError as exc:
            raise RegistryAppError("conflict", str(exc), http_status=409) from exc
        payload = org_to_dict(org)
        payload["role"] = mem.role
        payload["membership"] = membership_to_dict(mem)
        return payload

    def list_members(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        org = self.orgs.get_org(org_id)
        if org is None:
            raise RegistryAppError("not_found", "org not found", http_status=404)
        if not AccessPolicy.is_admin(auth.scopes) and (
            not auth.user_id or self.orgs.membership(org_id, auth.user_id) is None
        ):
            raise RegistryAppError("not_found", "org not found", http_status=404)
        member_rows = self.orgs.list_members(org_id)
        profiles = self.orgs.get_user_profiles([m.user_id for m in member_rows])
        members = [membership_to_dict(m, profile=profiles.get(m.user_id)) for m in member_rows]
        return {"org_id": org_id, "items": members}

    def add_member(
        self, *, org_id: str, user_id: str, role: str, auth: TokenInfo
    ) -> dict[str, Any]:
        org_id = org_id.casefold()
        if not auth.user_id and not AccessPolicy.is_admin(auth.scopes):
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        mem = self.orgs.membership(org_id, auth.user_id) if auth.user_id else None
        if not AccessPolicy.is_admin(auth.scopes) and (mem is None or mem.role != "owner"):
            raise RegistryAppError(
                "forbidden",
                "owner required to add members",
                http_status=403,
            )
        target = _normalize_user_id(user_id)
        if not target:
            raise RegistryAppError("invalid_request", "user_id required", http_status=400)
        try:
            m = self.orgs.add_member(org_id, target, role=role or "member")
        except LookupError as exc:
            raise RegistryAppError("not_found", "org not found", http_status=404) from exc
        except ValueError as exc:
            code = "conflict" if "exists" in str(exc) else "invalid_request"
            status = 409 if code == "conflict" else 400
            raise RegistryAppError(code, str(exc), http_status=status) from exc
        return membership_to_dict(m)

    def set_member_role(
        self, *, org_id: str, user_id: str, role: str, auth: TokenInfo
    ) -> dict[str, Any]:
        org_id = org_id.casefold()
        if not auth.user_id and not AccessPolicy.is_admin(auth.scopes):
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        mem = self.orgs.membership(org_id, auth.user_id) if auth.user_id else None
        if not AccessPolicy.is_admin(auth.scopes) and (mem is None or mem.role != "owner"):
            raise RegistryAppError(
                "forbidden",
                "owner required to change member role",
                http_status=403,
            )
        target = _normalize_user_id(user_id)
        if not target:
            raise RegistryAppError("invalid_request", "user_id required", http_status=400)
        wanted = (role or "").strip().casefold()
        if wanted not in {"owner", "member"}:
            raise RegistryAppError(
                "invalid_request",
                "role must be owner or member",
                http_status=400,
            )
        try:
            m = self.orgs.set_member_role(org_id, target, role=wanted)
        except LookupError as exc:
            raise RegistryAppError("not_found", "membership not found", http_status=404) from exc
        except PermissionError as exc:
            raise RegistryAppError("forbidden", str(exc), http_status=403) from exc
        except ValueError as exc:
            raise RegistryAppError("invalid_request", str(exc), http_status=400) from exc
        return membership_to_dict(m)

    def transfer(self, *, org_id: str, user_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "user identity required", http_status=401)
        caller = self.orgs.membership(org_id, auth.user_id)
        if caller is None or caller.role != "owner":
            raise RegistryAppError(
                "forbidden",
                "owner required to transfer",
                http_status=403,
            )
        target = _normalize_user_id(user_id)
        if not target:
            raise RegistryAppError("invalid_request", "user_id required", http_status=400)
        if target == auth.user_id:
            raise RegistryAppError(
                "invalid_request",
                "cannot transfer to self",
                http_status=400,
            )
        try:
            new_target, new_caller = self.orgs.transfer_owner(
                org_id, from_user_id=auth.user_id, to_user_id=target
            )
        except LookupError as exc:
            msg = str(exc)
            if "caller" in msg:
                raise RegistryAppError("not_found", msg, http_status=404) from exc
            raise RegistryAppError(
                "not_found",
                "target must be an existing member",
                http_status=404,
            ) from exc
        except PermissionError as exc:
            raise RegistryAppError("forbidden", str(exc), http_status=403) from exc
        except ValueError as exc:
            raise RegistryAppError("invalid_request", str(exc), http_status=400) from exc
        return {
            "ok": True,
            "org_id": org_id,
            "from": membership_to_dict(new_caller),
            "to": membership_to_dict(new_target),
        }

    def remove_member(self, *, org_id: str, user_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        target = _normalize_user_id(user_id) or user_id.casefold()
        mem = self.orgs.membership(org_id, auth.user_id) if auth.user_id else None
        if not AccessPolicy.is_admin(auth.scopes) and (mem is None or mem.role != "owner"):
            raise RegistryAppError(
                "forbidden",
                "owner required to remove members",
                http_status=403,
            )
        try:
            self.orgs.remove_member(org_id, target)
        except LookupError as exc:
            raise RegistryAppError("not_found", "membership not found", http_status=404) from exc
        except PermissionError as exc:
            raise RegistryAppError("forbidden", str(exc), http_status=403) from exc
        return {"ok": True, "org_id": org_id, "user_id": target}

    def leave(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        if not auth.user_id:
            raise RegistryAppError("unauthorized", "user identity required", http_status=401)
        try:
            self.orgs.leave_org(org_id, auth.user_id)
        except LookupError as exc:
            raise RegistryAppError("not_found", "membership not found", http_status=404) from exc
        except PermissionError as exc:
            raise RegistryAppError("forbidden", str(exc), http_status=403) from exc
        return {"ok": True, "org_id": org_id, "left": True}

    def delete(self, *, org_id: str, auth: TokenInfo) -> dict[str, Any]:
        org_id = org_id.casefold()
        self._require_owner(org_id, auth)
        try:
            self.orgs.delete_org(org_id)
        except LookupError as exc:
            raise RegistryAppError("not_found", "org not found", http_status=404) from exc
        except ValueError as exc:
            raise RegistryAppError("conflict", str(exc), http_status=409) from exc
        return {"ok": True, "org_id": org_id, "dissolved": True}

    def _require_owner(self, org_id: str, auth: TokenInfo) -> None:
        status = self.access.org_owner_status(org_id=org_id, auth=auth)
        if status == "ok":
            return
        if status == "not_found":
            raise RegistryAppError("not_found", "org not found", http_status=404)
        if status == "unauthorized":
            raise RegistryAppError("unauthorized", "login required", http_status=401)
        raise RegistryAppError("forbidden", "owner required", http_status=403)
