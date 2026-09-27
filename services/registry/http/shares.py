"""Snapshot share HTTP handlers. Dispatch is the only HTTP entry."""

from __future__ import annotations

import shutil

from services.registry.auth.tokens import TokenInfo
from services.registry.errors import RegistryAppError
from services.registry.http.dispatch import HttpResult, _caught, json_result


class ShareHandlers:
    def _create_snapshot_share(self, *, auth: TokenInfo) -> HttpResult:
        work: Path | None = None
        try:
            with self.state.upload_slots.hold():
                parsed = self._read_multipart_archive()
                if isinstance(parsed, HttpResult):
                    return parsed
                meta, archive, work = parsed
                payload = self.state.shares.create(meta=meta, archive=archive, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        return json_result(201, payload)
    def _find_snapshot_share(self, *, auth: TokenInfo, qs: dict[str, list[str]]) -> HttpResult:
        unknown = set(qs) - {"suite_run_id", "run_id"}
        if unknown:
            return json_result(
                400,
                {
                    "error": "invalid_request",
                    "message": "unknown keys: " + ", ".join(sorted(unknown)),
                },
            )
        suite_run_id = str((qs.get("suite_run_id") or [""])[0]).strip()
        run_id = str((qs.get("run_id") or [""])[0]).strip()
        if not suite_run_id:
            return json_result(
                400,
                {"error": "invalid_request", "message": "suite_run_id is required"},
            )
        try:
            payload = self.state.shares.find_owned(
                auth=auth, suite_run_id=suite_run_id, run_id=run_id
            )
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _get_snapshot_share(self, *, token: str) -> HttpResult:
        try:
            payload = self.state.shares.get(token)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _get_snapshot_attempt(self, *, token: str, run_id: str) -> HttpResult:
        try:
            payload = self.state.shares.attempt_meta(token, run_id)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _list_snapshot_attempt_files(self, *, token: str, run_id: str) -> HttpResult:
        try:
            payload = self.state.shares.list_attempt_files(token, run_id)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _read_snapshot_attempt_file(self, *, token: str, run_id: str, file_path: str) -> HttpResult:
        try:
            payload = self.state.shares.read_attempt_file(token, run_id, file_path)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
    def _revoke_snapshot_share(self, *, token: str, auth: TokenInfo) -> HttpResult:
        try:
            payload = self.state.shares.revoke(token, auth=auth)
        except RegistryAppError as exc:
            return _caught(exc)
        return json_result(200, payload)
