"""Org + user aggregate persistence: orgs, memberships, invite keys, user profiles."""

from __future__ import annotations

import sqlite3
from typing import Any

from services.registry import queries as Q
from services.registry.clock import now
from services.registry.protocols import OrgStoreProtocol
from services.registry.rows import (
    MembershipRow,
    OrgInviteKeyRow,
    OrgRow,
    UserProfileRow,
)
from services.registry.tokens import _normalize_user_id


class OrgStore(OrgStoreProtocol):
    """Org + user aggregate persistence: orgs, memberships, invite keys, user profiles."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

    def create_org(
        self,
        *,
        name: str,
        owner_user_id: str,
        display_name: str = "",
        description: str = "",
        is_claimable: bool = False,
    ) -> OrgRow:
        org_id = name
        row = OrgRow(
            org_id=org_id,
            name=name,
            display_name=display_name or name,
            description=description,
            is_claimable=is_claimable,
            created_at=now(),
        )
        with self._connect() as conn:
            try:
                self._exec(
                    conn,
                    Q.INSERT_ORG,
                    (
                        row.org_id,
                        row.name,
                        row.display_name,
                        row.description,
                        1 if row.is_claimable else 0,
                        row.created_at,
                    ),
                )
                self._exec(
                    conn,
                    Q.INSERT_ORG_OWNER_MEMBERSHIP,
                    (row.org_id, owner_user_id, row.created_at),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("org already exists") from exc
        return row

    def update_org_display_name(self, org_id: str, display_name: str) -> OrgRow:
        return self.update_org(org_id, display_name=display_name)

    def update_org(
        self,
        org_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        icon_key: str | None = None,
        icon_github: str | None = None,
    ) -> OrgRow:
        has_name = display_name is not None
        has_desc = description is not None
        has_icons = icon_key is not None or icon_github is not None
        if not (has_name or has_desc or has_icons):
            raise ValueError("nothing to update")
        params: list[str] = []
        if has_name:
            params.append(display_name or "")
        if has_desc:
            params.append(description or "")
        if has_icons:
            params.append(icon_key or "")
            params.append(icon_github or "")
        params.append(org_id)
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.update_org_query(display_name=has_name, description=has_desc, icons=has_icons),
                tuple(params),
            )
            if getattr(cur, "rowcount", 1) == 0:
                raise LookupError("org not found")
            conn.commit()
        org = self.get_org(org_id)
        if org is None:
            raise LookupError("org not found")
        return org

    def get_org(self, org_id: str) -> OrgRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_ORG, (org_id,))
            r = cur.fetchone()
            return self._org_row(r) if r else None

    def list_orgs_for_user(self, user_id: str) -> list[tuple[OrgRow, str]]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_USER_ORGS, (user_id,))
            out: list[tuple[OrgRow, str]] = []
            for r in cur.fetchall():
                out.append((self._org_row(r), str(r["membership_role"])))
            return out

    def claim_org(self, org_id: str, user_id: str) -> OrgRow:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_ORG, (org_id,))
            r = cur.fetchone()
            if r is None:
                raise LookupError("org not found")
            org = self._org_row(r)
            if not org.is_claimable:
                raise PermissionError("org not claimable")
            owners = self._exec(
                conn,
                Q.SELECT_ORG_HAS_OWNER,
                (org_id,),
            ).fetchone()
            if owners is not None:
                raise PermissionError("org already claimed")
            self._exec(
                conn,
                Q.INSERT_ORG_MEMBERSHIP_OWNER,
                (org_id, user_id, now()),
            )
            self._exec(
                conn,
                Q.UPDATE_ORG_CLAIMED,
                (org_id,),
            )
            conn.commit()
        got = self.get_org(org_id)
        assert got is not None
        return got

    def add_member(self, org_id: str, user_id: str, *, role: str = "member") -> MembershipRow:
        if role not in {"owner", "member"}:
            raise ValueError("invalid role")
        ts = now()
        with self._connect() as conn:
            if self.get_org(org_id) is None:
                raise LookupError("org not found")
            try:
                self._exec(
                    conn,
                    Q.INSERT_ORG_MEMBERSHIP,
                    (org_id, user_id, role, ts),
                )
                conn.commit()
            except self._adapter.integrity_error as exc:
                raise ValueError("membership exists") from exc
        return MembershipRow(org_id=org_id, user_id=user_id, role=role, created_at=ts)

    def set_member_role(self, org_id: str, user_id: str, *, role: str) -> MembershipRow:
        if role not in {"owner", "member"}:
            raise ValueError("invalid role")
        uid = _normalize_user_id(user_id) or user_id
        mem = self.membership(org_id, uid)
        if mem is None:
            raise LookupError("membership not found")
        if mem.role == role:
            return mem
        if mem.role == "owner" and role == "member" and self.count_org_owners(org_id) <= 1:
            raise PermissionError("sole owner cannot be demoted; dissolve the organization instead")
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.UPDATE_ORG_MEMBERSHIP_ROLE,
                (role, org_id, uid),
            )
            if cur.rowcount == 0:
                raise LookupError("membership not found")
            conn.commit()
        updated = self.membership(org_id, uid)
        if updated is None:
            raise LookupError("membership not found")
        return updated

    def transfer_owner(
        self, org_id: str, *, from_user_id: str, to_user_id: str
    ) -> tuple[MembershipRow, MembershipRow]:
        """Atomic: target → owner, caller → member. Target must already be a member."""
        src = _normalize_user_id(from_user_id) or from_user_id
        dst = _normalize_user_id(to_user_id) or to_user_id
        if not src or not dst:
            raise ValueError("user_id required")
        if src == dst:
            raise ValueError("cannot transfer to self")
        target = self.membership(org_id, dst)
        if target is None:
            raise LookupError("membership not found")
        caller = self.membership(org_id, src)
        if caller is None:
            raise LookupError("caller membership not found")
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPDATE_ORG_MEMBERSHIP_ROLE,
                ("owner", org_id, dst),
            )
            self._exec(
                conn,
                Q.UPDATE_ORG_MEMBERSHIP_ROLE,
                ("member", org_id, src),
            )
            conn.commit()
        new_target = self.membership(org_id, dst)
        new_caller = self.membership(org_id, src)
        if new_target is None or new_caller is None:
            raise LookupError("membership not found")
        return new_target, new_caller

    def remove_member(self, org_id: str, user_id: str) -> None:
        uid = _normalize_user_id(user_id) or user_id
        mem = self.membership(org_id, uid)
        if mem is None:
            raise LookupError("membership not found")
        if mem.role == "owner" and self.count_org_owners(org_id) <= 1:
            raise PermissionError("sole owner cannot be removed; dissolve the organization instead")
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.DELETE_ORG_MEMBERSHIP,
                (org_id, uid),
            )
            if cur.rowcount == 0:
                raise LookupError("membership not found")
            conn.commit()

    def count_org_owners(self, org_id: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_ORG_OWNERS,
                (org_id,),
            )
            r = cur.fetchone()
            return int(r["n"] if r is not None else 0)

    def count_org_packages(self, org_id: str) -> int:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.COUNT_ORG_PACKAGES,
                (org_id,),
            )
            r = cur.fetchone()
            return int(r["n"] if r is not None else 0)

    def leave_org(self, org_id: str, user_id: str) -> None:
        """Member (or non-sole owner) leaves the org."""
        uid = _normalize_user_id(user_id) or user_id
        mem = self.membership(org_id, uid)
        if mem is None:
            raise LookupError("membership not found")
        if mem.role == "owner" and self.count_org_owners(org_id) <= 1:
            raise PermissionError("sole owner cannot leave; dissolve the organization instead")
        self.remove_member(org_id, uid)

    def delete_org(self, org_id: str) -> None:
        """Dissolve org: memberships + invite keys + org row. Fail if packages remain."""
        if self.get_org(org_id) is None:
            raise LookupError("org not found")
        n_pkg = self.count_org_packages(org_id)
        if n_pkg > 0:
            raise ValueError(
                f"org still has {n_pkg} package release(s); unpublish or reassign first"
            )
        with self._connect() as conn:
            self._exec(conn, Q.DELETE_ORG_INVITE_KEYS, (org_id,))
            self._exec(conn, Q.DELETE_ORG_MEMBERSHIPS, (org_id,))
            self._exec(conn, Q.DELETE_ORG_RESULT_SHARES, (org_id,))
            cur = self._exec(conn, Q.DELETE_ORG, (org_id,))
            if cur.rowcount == 0:
                raise LookupError("org not found")
            conn.commit()

    def list_members(self, org_id: str) -> list[MembershipRow]:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_ORG_MEMBERS,
                (org_id,),
            )
            return [
                MembershipRow(
                    org_id=str(r["org_id"]),
                    user_id=str(r["user_id"]),
                    role=str(r["role"]),
                    created_at=float(r["created_at"]),
                )
                for r in cur.fetchall()
            ]

    def membership(self, org_id: str, user_id: str) -> MembershipRow | None:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_MEMBERSHIP, (org_id, user_id))
            r = cur.fetchone()
            if r is None:
                return None
            return MembershipRow(
                org_id=str(r["org_id"]),
                user_id=str(r["user_id"]),
                role=str(r["role"]),
                created_at=float(r["created_at"]),
            )

    def create_invite_key(
        self,
        *,
        org_id: str,
        created_by: str,
        token_hash: str,
        token_prefix: str,
        max_uses: int | None = None,
        expires_at: float | None = None,
        key_id: str | None = None,
    ) -> OrgInviteKeyRow:
        import secrets as _secrets

        if self.get_org(org_id) is None:
            raise LookupError("org not found")
        if max_uses is not None and max_uses < 1:
            raise ValueError("max_uses must be >= 1")
        if not token_hash or not token_prefix:
            raise ValueError("token_hash and token_prefix required")
        kid = key_id or _secrets.token_hex(8)
        row = OrgInviteKeyRow(
            key_id=kid,
            org_id=org_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            created_by=created_by or "",
            max_uses=max_uses,
            use_count=0,
            expires_at=expires_at,
            revoked_at=None,
            created_at=now(),
        )
        with self._connect() as conn:
            self._exec(
                conn,
                Q.INSERT_INVITE_KEY,
                (
                    row.key_id,
                    row.org_id,
                    row.token_hash,
                    row.token_prefix,
                    row.created_by,
                    row.max_uses,
                    row.use_count,
                    row.expires_at,
                    row.revoked_at,
                    row.created_at,
                ),
            )
            conn.commit()
        return row

    def list_invite_keys(self, org_id: str) -> list[OrgInviteKeyRow]:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_KEYS,
                (org_id,),
            )
            return [self._invite_key_row(r) for r in cur.fetchall()]

    def get_invite_key(self, org_id: str, key_id: str) -> OrgInviteKeyRow | None:
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_KEY,
                (org_id, key_id),
            )
            r = cur.fetchone()
            return self._invite_key_row(r) if r else None

    def revoke_invite_key(self, org_id: str, key_id: str) -> OrgInviteKeyRow:
        ts = now()
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_KEY,
                (org_id, key_id),
            )
            r = cur.fetchone()
            if r is None:
                raise LookupError("invite key not found")
            row = self._invite_key_row(r)
            if row.revoked_at is not None:
                return row
            self._exec(
                conn,
                Q.UPDATE_INVITE_REVOKED,
                (ts, key_id),
            )
            conn.commit()
        out = self.get_invite_key(org_id, key_id)
        assert out is not None
        return out

    def redeem_invite_key(self, *, token_hash: str, user_id: str) -> tuple[OrgRow, MembershipRow]:
        """Join org via invite key. Fail closed on expired / exhausted / revoked.

        ``max_uses`` is enforced by a conditional ``UPDATE`` so concurrent
        redeems cannot over-admit under multi-writer backends.
        """
        uid = _normalize_user_id(user_id) or user_id
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_INVITE_BY_HASH,
                (token_hash,),
            )
            r = cur.fetchone()
            if r is None:
                raise LookupError("invalid invite key")
            inv = self._invite_key_row(r)
            if inv.revoked_at is not None:
                raise PermissionError("invite key revoked")
            if inv.expires_at is not None and inv.expires_at <= now():
                raise PermissionError("invite key expired")
            org = self.get_org(inv.org_id)
            if org is None:
                raise LookupError("org not found")
            existing = self.membership(inv.org_id, uid)
            if existing is not None:
                # Already a member: do not burn use_count.
                return org, existing
            # Claim a slot atomically (check + increment). rowcount==0 ⇒ exhausted.
            claim = self._exec(
                conn,
                Q.CLAIM_INVITE_USE,
                (inv.key_id,),
            )
            if claim.rowcount == 0:
                raise PermissionError("invite key exhausted")
            ts = now()
            try:
                self._exec(
                    conn,
                    Q.INSERT_ORG_MEMBERSHIP_MEMBER,
                    (inv.org_id, uid, ts),
                )
            except self._adapter.integrity_error as exc:
                # Same-transaction rollback drops the claim on context exit.
                raise ValueError("membership exists") from exc
            conn.commit()
            mem = MembershipRow(org_id=inv.org_id, user_id=uid, role="member", created_at=ts)
            return org, mem

    @staticmethod
    def _invite_key_row(r: sqlite3.Row) -> OrgInviteKeyRow:
        max_uses = r["max_uses"]
        expires_at = r["expires_at"]
        revoked_at = r["revoked_at"]
        return OrgInviteKeyRow(
            key_id=str(r["key_id"]),
            org_id=str(r["org_id"]),
            token_hash=str(r["token_hash"]),
            token_prefix=str(r["token_prefix"] or ""),
            created_by=str(r["created_by"] or ""),
            max_uses=int(max_uses) if max_uses is not None else None,
            use_count=int(r["use_count"] or 0),
            expires_at=float(expires_at) if expires_at is not None else None,
            revoked_at=float(revoked_at) if revoked_at is not None else None,
            created_at=float(r["created_at"]),
        )

    def user_org_ids(self, user_id: str) -> set[str]:
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_USER_ORG_IDS, (user_id,))
            return {str(r["org_id"]) for r in cur.fetchall()}

    # ---- result shares ---------------------------------------------------

    @staticmethod
    def _org_row(r: sqlite3.Row) -> OrgRow:
        keys = r.keys()
        return OrgRow(
            org_id=str(r["org_id"]),
            name=str(r["name"]),
            display_name=str(r["display_name"] or ""),
            description=str(r["description"] or ""),
            is_claimable=bool(int(r["is_claimable"])),
            created_at=float(r["created_at"]),
            icon_key=str(r["icon_key"]) if "icon_key" in keys else "",
            icon_github=str(r["icon_github"]) if "icon_github" in keys else "",
        )

    def upsert_user_profile(
        self,
        *,
        user_id: str,
        display_name: str = "",
        avatar_url: str = "",
        github_id: str = "",
    ) -> UserProfileRow:
        uid = _normalize_user_id(user_id) or user_id
        row = UserProfileRow(
            user_id=uid,
            display_name=(display_name or "").strip(),
            avatar_url=(avatar_url or "").strip(),
            github_id=str(github_id or "").strip(),
            description="",
            updated_at=now(),
        )
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_USER_PROFILE,
                (
                    row.user_id,
                    row.display_name,
                    row.avatar_url,
                    row.github_id,
                    row.updated_at,
                ),
            )
            conn.commit()
        stored = self.get_user_profile(uid)
        if stored is None:
            raise LookupError("user not found")
        return stored

    def get_user_profile(self, user_id: str) -> UserProfileRow | None:
        uid = _normalize_user_id(user_id) or user_id
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.SELECT_USER_PROFILE,
                (uid,),
            )
            r = cur.fetchone()
            if r is None:
                return None
            return UserProfileRow(
                user_id=str(r["user_id"]),
                display_name=str(r["display_name"] or ""),
                avatar_url=str(r["avatar_url"] or ""),
                github_id=str(r["github_id"] or ""),
                description=str(r["description"] or ""),
                updated_at=float(r["updated_at"]),
            )

    def set_user_description(self, user_id: str, description: str) -> UserProfileRow:
        uid = _normalize_user_id(user_id) or user_id
        with self._connect() as conn:
            self._exec(
                conn,
                Q.UPSERT_USER_DESCRIPTION,
                (uid, description, now()),
            )
            conn.commit()
        row = self.get_user_profile(uid)
        if row is None:
            raise LookupError("user not found")
        return row

    def get_user_profiles(self, user_ids: list[str] | set[str]) -> dict[str, UserProfileRow]:
        ids = sorted({_normalize_user_id(u) or u for u in user_ids if u})
        if not ids:
            return {}
        with self._connect() as conn:
            cur = self._exec(
                conn,
                Q.select_user_profiles_in_query(len(ids)),
                ids,
            )
            out: dict[str, UserProfileRow] = {}
            for r in cur.fetchall():
                p = UserProfileRow(
                    user_id=str(r["user_id"]),
                    display_name=str(r["display_name"] or ""),
                    avatar_url=str(r["avatar_url"] or ""),
                    github_id=str(r["github_id"] or ""),
                    description=str(r["description"] or ""),
                    updated_at=float(r["updated_at"]),
                )
                out[p.user_id] = p
            return out
