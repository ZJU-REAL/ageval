"""Org and user HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result


class OrgHandlers:
    def _get_user(self, *, user_id: str) -> HttpResult:
        try:
            payload = self.state.users.get_public(user_id)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _create_org(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [
            key
            for key in body
            if key not in {"name", "display_name", "is_claimable", "description"}
        ]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        try:
            payload = self.state.orgs.create(
                name=str(body.get("name") or ""),
                display_name=str(body.get("display_name") or ""),
                is_claimable=bool(body.get("is_claimable", False)),
                description=body.get("description", ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)
    def _list_orgs(self, *, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.list_for_user(auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _get_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.get_public(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [
            key
            for key in body
            if key not in {"display_name", "description", "icon_key", "icon_github"}
        ]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        try:
            payload = self.state.orgs.patch(
                org_id=org_id,
                display_name=body["display_name"] if "display_name" in body else None,  # noqa: SIM401
                description=body["description"] if "description" in body else None,  # noqa: SIM401
                icon_key=body.get("icon_key"),
                icon_github=body.get("icon_github"),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_user(self, *, user_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [key for key in body if key not in {"description"}]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        if "description" not in body:
            return json_result(400, {"error": "invalid_request", "message": "description required"})
        try:
            payload = self.state.users.patch(
                user_id=user_id,
                description=body["description"],
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _claim_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.claim(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _create_invite_key(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.create_invite(
                org_id=org_id,
                max_uses=body.get("max_uses"),
                expires_at=body.get("expires_at"),
                expires_in_days=body.get("expires_in_days"),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)
    def _list_invite_keys(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.list_invites(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _revoke_invite_key(self, *, org_id: str, key_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.revoke_invite(org_id=org_id, key_id=key_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _join_org_with_invite(self, *, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.join(
                invite_key=str(body.get("invite_key") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _list_org_members(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.list_members(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _add_org_member(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.add_member(
                org_id=org_id,
                user_id=str(body.get("user_id") or ""),
                role=str(body.get("role") or "member"),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)
    def _remove_org_member(self, *, org_id: str, user_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.remove_member(org_id=org_id, user_id=user_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_org_member(self, *, org_id: str, user_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.set_member_role(
                org_id=org_id,
                user_id=user_id,
                role=str(body.get("role") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _transfer_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.orgs.transfer(
                org_id=org_id,
                user_id=str(body.get("user_id") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _leave_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.leave(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _delete_org(self, *, org_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.orgs.delete(org_id=org_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
