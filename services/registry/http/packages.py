"""Package HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

import shutil

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result, octet_result
from services.registry.paging import parse_limit, parse_offset


class PackageHandlers:
    def _publish_package(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.packages.publish(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)
    def _release_draft(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.packages.release_draft(
                dataset_id=dataset_id,
                auth=auth,
                visibility=str(body.get("visibility") or "") or None,
                replace=bool(body.get("replace")),
                version=str(body.get("version") or "") or None,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)
    def _put_package_favorite(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.packages.set_favorite(
                dataset_id=dataset_id, auth=auth, favorited=True
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _delete_package_favorite(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.packages.set_favorite(
                dataset_id=dataset_id, auth=auth, favorited=False
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _list_packages(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        try:
            mine_raw = (qs.get("mine") or [""])[0]
            fav_raw = (qs.get("favorited") or [""])[0]
            orgs_raw = (qs.get("orgs") or [""])[0]
            payload = self.state.packages.list_packages(
                auth=auth,
                prefix=(qs.get("dataset_id_prefix") or [None])[0],
                visibility=(qs.get("visibility") or [None])[0],
                version=(qs.get("version") or [None])[0],
                package_kind=(qs.get("package_kind") or [None])[0],
                mine=str(mine_raw).strip().lower() in {"1", "true", "yes"},
                favorited=str(fav_raw).strip().lower() in {"1", "true", "yes"},
                orgs=str(orgs_raw).strip().lower() in {"1", "true", "yes"},
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _list_package_versions(
        self, *, dataset_id: str, auth: TokenInfo, qs: dict[str, list[str]]
    ) -> HttpResult:
        try:
            package_kind = (qs.get("package_kind") or [None])[0]
            payload = self.state.packages.list_versions(
                dataset_id=dataset_id,
                auth=auth,
                package_kind=package_kind,
            )
            items = payload.get("items") or []
            if any(
                isinstance(item, dict) and item.get("package_kind") == "agent" for item in items
            ):
                payload["performances"] = self.state.runtimes.performances_for_agent(
                    dataset_id, auth
                )
                collect = self.state.runtimes.collect_payload(dataset_id, auth)
                if collect is not None:
                    payload["performance_collect"] = collect
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_meta(
        self,
        *,
        dataset_id: str,
        version: str | None,
        package_digest: str | None,
        auth: TokenInfo,
    ) -> HttpResult:
        try:
            payload = self.state.packages.serve_meta(
                dataset_id=dataset_id,
                version=version,
                package_digest=package_digest,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_content(
        self, *, dataset_id: str, package_digest: str, auth: TokenInfo
    ) -> HttpResult:
        try:
            fh, size, row = self.state.packages.serve_content(
                dataset_id=dataset_id,
                package_digest=package_digest,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return octet_result(
            None,
            {"X-Ageval-Blob-Digest": row.blob_digest},
            stream=fh,
            size=size,
        )
    def _serve_package_files_list(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
        qs: dict[str, list[str]] | None = None,
    ) -> HttpResult:
        try:
            package_kind = (qs.get("package_kind") or [None])[0] if qs else None
            payload = self.state.packages.list_files(
                dataset_id=dataset_id,
                auth=auth,
                package_digest=package_digest,
                version=version,
                package_kind=package_kind,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_package_tasks(
        self,
        *,
        dataset_id: str,
        auth: TokenInfo,
        qs: dict[str, list[str]],
        package_digest: str | None = None,
        version: str | None = None,
    ) -> HttpResult:
        extra = set(qs) - {"limit", "offset", "q"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        try:
            payload = self.state.packages.list_tasks(
                dataset_id=dataset_id,
                auth=auth,
                package_digest=package_digest,
                version=version,
                limit=parse_limit((qs.get("limit") or [None])[0]),
                offset=parse_offset((qs.get("offset") or [None])[0]),
                q=(qs.get("q") or [None])[0],
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_package_file(
        self,
        *,
        dataset_id: str,
        file_path: str,
        auth: TokenInfo,
        package_digest: str | None = None,
        version: str | None = None,
        qs: dict[str, list[str]] | None = None,
    ) -> HttpResult:
        try:
            package_kind = (qs.get("package_kind") or [None])[0] if qs else None
            payload = self.state.packages.read_file(
                dataset_id=dataset_id,
                file_path=file_path,
                auth=auth,
                package_digest=package_digest,
                version=version,
                package_kind=package_kind,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_package_display_name(self, *, dataset_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        unknown = [
            key
            for key in body
            if key not in {"display_name", "icon_key", "icon_github", "description"}
        ]
        if unknown:
            return json_result(400, {"error": "invalid_request", "message": "unknown keys"})
        has_display_name = "display_name" in body
        has_icon_key = "icon_key" in body
        has_icon_github = "icon_github" in body
        has_description = "description" in body
        if not any([has_display_name, has_icon_key, has_icon_github, has_description]):
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "display_name or icon_key or icon_github or description required",
                },
            )
        try:
            payload = self.state.packages.patch_marketplace(
                dataset_id=dataset_id,
                display_name=body.get("display_name"),
                icon_key=body.get("icon_key"),
                icon_github=body.get("icon_github"),
                description=body.get("description"),
                has_display_name=has_display_name,
                has_icon_key=has_icon_key,
                has_icon_github=has_icon_github,
                has_description=has_description,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _delete_package_release(
        self, *, dataset_id: str, version: str, auth: TokenInfo
    ) -> HttpResult:
        try:
            payload = self.state.packages.delete_release(
                dataset_id=dataset_id, version=version, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_package_release(
        self, *, dataset_id: str, version: str, auth: TokenInfo
    ) -> HttpResult:
        visibility = self._visibility_body()
        if isinstance(visibility, HttpResult):
            return visibility
        try:
            payload = self.state.packages.patch_visibility(
                dataset_id=dataset_id,
                version=version,
                visibility=visibility,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
