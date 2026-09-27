"""Result HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

import shutil

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result, octet_result
from services.registry.paging import parse_limit, parse_offset

from ageval.registry.media_types import (
    ATTEMPT_RESULT_MEDIA_TYPE as RESULT_MEDIA_TYPE,
)
from ageval.registry.media_types import SUITE_RESULT_MEDIA_TYPE


class ResultHandlers:
    def _upload_attempt(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.results.upload_attempt(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)
    def _list_attempts(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        try:
            payload = self.state.results.list_attempts(
                auth=auth,
                dataset_id=(qs.get("dataset_id") or [None])[0],
                task_id=(qs.get("task_id") or [None])[0],
                standalone=(qs.get("standalone") or ["0"])[0] in {"1", "true", "yes"},
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_attempt_meta(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.serve_attempt_meta(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_attempt_content(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            fh, size, row = self.state.results.serve_attempt_content(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return octet_result(
            None,
            {
                "X-Ageval-Blob-Digest": row.blob_digest,
                "X-Ageval-Media-Type": RESULT_MEDIA_TYPE,
            },
            stream=fh,
            size=size,
        )
    def _serve_attempt_files_list(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.list_attempt_files(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_attempt_file(self, *, run_id: str, file_path: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.read_attempt_file(
                run_id=run_id, file_path=file_path, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _upload_suite(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.results.upload_suite(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)
    def _append_suite_slot(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.results.append_suite_slot(
                suite_run_id=suite_run_id, body=body, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _list_suites(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        try:
            board_raw = (qs.get("board") or [""])[0]
            payload = self.state.results.list_suites(
                auth=auth,
                dataset_id=(qs.get("dataset_id") or [None])[0],
                board=str(board_raw).strip().lower() in {"1", "true", "yes"},
                uploaded_by=(qs.get("uploaded_by") or [None])[0],
                task_id=(qs.get("task_id") or [None])[0],
                limit=parse_limit((qs.get("limit") or [None])[0], default=None),
                offset=parse_offset((qs.get("offset") or [None])[0]),
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_suite_meta(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.serve_suite_meta(suite_run_id=suite_run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _serve_suite_content(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            fh, size, row = self.state.results.serve_suite_content(
                suite_run_id=suite_run_id, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return octet_result(
            None,
            {
                "X-Ageval-Blob-Digest": row.blob_digest,
                "X-Ageval-Media-Type": SUITE_RESULT_MEDIA_TYPE,
            },
            stream=fh,
            size=size,
        )
    def _list_result_shares(
        self, *, result_kind: str, result_id: str, auth: TokenInfo
    ) -> HttpResult:
        try:
            payload = self.state.results.list_shares(
                result_kind=result_kind, result_id=result_id, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _add_result_share(self, *, result_kind: str, result_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.results.add_share(
                result_kind=result_kind,
                result_id=result_id,
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(201, payload)
    def _remove_result_share(
        self, *, result_kind: str, result_id: str, auth: TokenInfo
    ) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        try:
            payload = self.state.results.remove_share(
                result_kind=result_kind,
                result_id=result_id,
                target_type=str(body.get("target_type") or ""),
                target_id=str(body.get("target_id") or ""),
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _delete_attempt(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.results.delete_attempt(run_id=run_id, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _delete_suite(
        self, *, suite_run_id: str, auth: TokenInfo, qs: dict[str, list[str]]
    ) -> HttpResult:
        with_attempts = (qs.get("with_attempts") or ["0"])[0] in {"1", "true", "yes"}
        try:
            payload = self.state.results.delete_suite(
                suite_run_id=suite_run_id,
                with_attempts=with_attempts,
                auth=auth,
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_attempt(self, *, run_id: str, auth: TokenInfo) -> HttpResult:
        visibility = self._visibility_body()
        if isinstance(visibility, HttpResult):
            return visibility
        try:
            payload = self.state.results.patch_attempt(
                run_id=run_id, visibility=visibility, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _attach_suite_agent(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        body = self._read_json_body()
        if isinstance(body, HttpResult):
            return body
        extra = set(body) - {"agent", "role"}
        if extra:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(extra)),
                },
            )
        agent = str(body.get("agent") or "").strip()
        if not agent:
            return json_result(400, {"error": "invalid_request", "message": "agent is required"})
        role_raw = body.get("role")
        role = str(role_raw).strip() if isinstance(role_raw, str) and role_raw.strip() else None
        try:
            payload = self.state.results.attach_agent(
                suite_run_id=suite_run_id, agent=agent, role=role, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _patch_suite(self, *, suite_run_id: str, auth: TokenInfo) -> HttpResult:
        visibility = self._visibility_body()
        if isinstance(visibility, HttpResult):
            return visibility
        try:
            payload = self.state.results.patch_suite(
                suite_run_id=suite_run_id, visibility=visibility, auth=auth
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
