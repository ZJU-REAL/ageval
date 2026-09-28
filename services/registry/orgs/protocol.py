"""Org store protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from services.registry.orgs.rows import (
        MembershipRow,
        OrgInviteKeyRow,
        OrgRow,
        UserProfileRow,
    )


@runtime_checkable
class OrgStoreProtocol(Protocol):
    def create_org(
        self,
        *,
        name: str,
        owner_user_id: str,
        display_name: str = "",
        description: str = "",
        is_claimable: bool = False,
    ) -> OrgRow: ...

    def update_org_display_name(self, org_id: str, display_name: str) -> OrgRow: ...

    def update_org(
        self,
        org_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        icon_key: str | None = None,
        icon_github: str | None = None,
    ) -> OrgRow: ...

    def get_org(self, org_id: str) -> OrgRow | None: ...

    def list_orgs_for_user(self, user_id: str) -> list[tuple[OrgRow, str]]: ...

    def claim_org(self, org_id: str, user_id: str) -> OrgRow: ...

    def add_member(self, org_id: str, user_id: str, *, role: str = "member") -> MembershipRow: ...

    def set_member_role(self, org_id: str, user_id: str, *, role: str) -> MembershipRow: ...

    def transfer_owner(
        self, org_id: str, *, from_user_id: str, to_user_id: str
    ) -> tuple[MembershipRow, MembershipRow]: ...

    def remove_member(self, org_id: str, user_id: str) -> None: ...

    def count_org_owners(self, org_id: str) -> int: ...

    def count_org_packages(self, org_id: str) -> int: ...

    def leave_org(self, org_id: str, user_id: str) -> None: ...

    def delete_org(self, org_id: str) -> None: ...

    def list_members(self, org_id: str) -> list[MembershipRow]: ...

    def membership(self, org_id: str, user_id: str) -> MembershipRow | None: ...

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
    ) -> OrgInviteKeyRow: ...

    def list_invite_keys(self, org_id: str) -> list[OrgInviteKeyRow]: ...

    def get_invite_key(self, org_id: str, key_id: str) -> OrgInviteKeyRow | None: ...

    def revoke_invite_key(self, org_id: str, key_id: str) -> OrgInviteKeyRow: ...

    def redeem_invite_key(
        self, *, token_hash: str, user_id: str
    ) -> tuple[OrgRow, MembershipRow]: ...

    def user_org_ids(self, user_id: str) -> set[str]: ...

    def upsert_user_profile(
        self,
        *,
        user_id: str,
        display_name: str = "",
        avatar_url: str = "",
        github_id: str = "",
    ) -> UserProfileRow: ...

    def get_user_profile(self, user_id: str) -> UserProfileRow | None: ...

    def set_user_description(self, user_id: str, description: str) -> UserProfileRow: ...

    def get_user_profiles(self, user_ids: list[str] | set[str]) -> dict[str, UserProfileRow]: ...
