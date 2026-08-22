"""HTTP(S) JSON client for the Dataset Registry service."""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ageval.registry.types import ReleaseInfo


class RegistryError(Exception):
    """Operator-facing registry client failure."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(f"{code}: {message}")


class RegistryClient:
    """Thin HTTP client. Never receives S3 credentials — only Registry API."""

    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self, *, content_type: str | None = None, auth: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | Any | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers=headers or self._headers(auth=auth),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read()
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return int(resp.status), raw, hdrs
        except urllib.error.HTTPError as exc:
            raw = exc.read() if exc.fp else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            code = str(payload.get("error") or "registry_http_error")
            msg = str(payload.get("message") or exc.reason or "HTTP error")
            # private concealment: 404 for unauthorized private
            raise RegistryError(code, msg, status=int(exc.code)) from exc
        except urllib.error.URLError as exc:
            raise RegistryError(
                "registry_unavailable",
                f"cannot reach registry: {exc.reason}",
            ) from exc

    def _put_multipart(
        self,
        path: str,
        *,
        meta: dict[str, Any],
        archive: Path,
        filename: str,
        boundary_prefix: str,
    ) -> tuple[int, bytes, dict[str, str]]:
        import secrets as _secrets

        boundary = f"{boundary_prefix}-{_secrets.token_hex(12)}"
        header = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="metadata"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        mid = (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="archive"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        meta_bytes = json.dumps(meta, sort_keys=True).encode()
        with tempfile.NamedTemporaryFile(prefix="ageval-mp-", suffix=".http", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with tmp_path.open("wb") as out, archive.open("rb") as inf:
                out.write(header)
                out.write(meta_bytes)
                out.write(mid)
                shutil.copyfileobj(inf, out)
                out.write(tail)
            size = tmp_path.stat().st_size
            headers = self._headers(
                content_type=f"multipart/form-data; boundary={boundary}",
                auth=True,
            )
            headers["Content-Length"] = str(size)
            with tmp_path.open("rb") as body:
                return self._request("POST", path, body=body, headers=headers)  # type: ignore[arg-type]
        finally:
            tmp_path.unlink(missing_ok=True)

    def _download_to(self, path: str, dest: Path) -> Path:
        dest = dest.expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET", headers=self._headers(auth=True))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp, tmp.open("wb") as out:  # noqa: S310
                shutil.copyfileobj(resp, out)
        except urllib.error.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raw = exc.read() if exc.fp else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            code = str(payload.get("error") or "registry_http_error")
            msg = str(payload.get("message") or exc.reason or "HTTP error")
            raise RegistryError(code, msg, status=int(exc.code)) from exc
        except urllib.error.URLError as exc:
            tmp.unlink(missing_ok=True)
            raise RegistryError(
                "registry_unavailable",
                f"cannot reach registry: {exc.reason}",
            ) from exc
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(dest)
        return dest

    def health(self) -> dict[str, Any]:
        status, raw, _ = self._request("GET", "/health", auth=False)
        if status != 200:
            raise RegistryError("registry_unavailable", f"health status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def publish(
        self,
        *,
        dataset_id: str,
        version: str,
        package_digest: str,
        blob_digest: str,
        size: int,
        media_type: str,
        visibility: str,
        archive: Path,
        org_id: str,
        replace: bool = False,
        package_kind: str = "dataset",
        slot: str | None = None,
    ) -> ReleaseInfo:
        meta: dict[str, Any] = {
            "dataset_id": dataset_id,
            "version": version,
            "package_digest": package_digest,
            "blob_digest": blob_digest,
            "size": size,
            "media_type": media_type,
            "visibility": visibility,
            "org_id": org_id,
            "package_kind": package_kind,
        }
        if replace:
            meta["replace"] = True
        if slot:
            meta["slot"] = slot
        status, raw, _ = self._put_multipart(
            "/v1/packages",
            meta=meta,
            archive=archive,
            filename="package.tar.gz",
            boundary_prefix="ageval",
        )
        if status not in {200, 201}:
            raise RegistryError("publish_failed", f"unexpected status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        return ReleaseInfo.from_payload(data)

    def release_draft(
        self,
        *,
        dataset_id: str,
        visibility: str | None = None,
        replace: bool = False,
        version: str | None = None,
    ) -> ReleaseInfo:
        body: dict[str, Any] = {}
        if visibility:
            body["visibility"] = visibility
        if replace:
            body["replace"] = True
        if version:
            body["version"] = version
        status, raw, _ = self._request(
            "POST",
            f"/v1/packages/{quote(dataset_id, safe='/')}/release",
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json", auth=True),
        )
        if status not in {200, 201}:
            raise RegistryError("release_failed", f"unexpected status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        return ReleaseInfo.from_payload(data)

    def get_metadata(
        self,
        *,
        dataset_id: str,
        version: str | None = None,
        package_digest: str | None = None,
    ) -> ReleaseInfo:
        if package_digest:
            dig = quote(package_digest, safe=":")
            path = f"/v1/packages/{quote(dataset_id, safe='/')}/by-digest/{dig}"
        elif version:
            ver = quote(version, safe="")
            path = f"/v1/packages/{quote(dataset_id, safe='/')}/versions/{ver}"
        else:
            raise RegistryError("invalid_ref", "version or package_digest required")
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("not_found", f"release not found ({status})", status=status)
        data = json.loads(raw.decode("utf-8"))
        return ReleaseInfo.from_payload(data)

    def fetch_content(self, *, dataset_id: str, package_digest: str, dest: Path) -> Path:
        path = (
            f"/v1/packages/{quote(dataset_id, safe='/')}"
            f"/by-digest/{quote(package_digest, safe=':')}/content"
        )
        return self._download_to(path, dest)

    def list_package_files(
        self,
        *,
        dataset_id: str,
        package_digest: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        """List package archive paths (Hub S2 / #38). Prefer immutable digest."""
        base = f"/v1/packages/{quote(dataset_id, safe='/')}"
        if package_digest:
            path = f"{base}/by-digest/{quote(package_digest, safe=':')}/files"
        elif version:
            path = f"{base}/versions/{quote(version, safe='')}/files"
        else:
            raise RegistryError("invalid_ref", "version or package_digest required")
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("not_found", f"files not found ({status})", status=status)
        return json.loads(raw.decode("utf-8"))

    def get_package_file(
        self,
        *,
        dataset_id: str,
        file_path: str,
        package_digest: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Read one package file as JSON envelope (utf-8 or base64)."""
        base = f"/v1/packages/{quote(dataset_id, safe='/')}"
        # Keep path segments; encode each for URL safety without collapsing slashes.
        encoded_file = "/".join(quote(seg, safe="") for seg in file_path.split("/"))
        if package_digest:
            path = f"{base}/by-digest/{quote(package_digest, safe=':')}/files/{encoded_file}"
        elif version:
            path = f"{base}/versions/{quote(version, safe='')}/files/{encoded_file}"
        else:
            raise RegistryError("invalid_ref", "version or package_digest required")
        status, raw, _ = self._request("GET", path, auth=True)
        if status == 413:
            raise RegistryError(
                "payload_too_large",
                f"file too large ({status})",
                status=status,
            )
        if status != 200:
            raise RegistryError("not_found", f"file not found ({status})", status=status)
        return json.loads(raw.decode("utf-8"))

    def list_packages(
        self,
        *,
        dataset_id_prefix: str | None = None,
        visibility: str | None = None,
        version: str | None = None,
    ) -> list[ReleaseInfo]:
        from urllib.parse import urlencode

        q: dict[str, str] = {}
        if dataset_id_prefix:
            q["dataset_id_prefix"] = dataset_id_prefix
        if visibility:
            q["visibility"] = visibility
        if version:
            q["version"] = version
        path = "/v1/packages"
        if q:
            path = f"{path}?{urlencode(q)}"
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("list_failed", f"status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RegistryError("list_failed", "invalid list response")
        return [self._release_from_dict(item) for item in items]

    def list_package_versions(self, dataset_id: str) -> list[ReleaseInfo]:
        path = f"/v1/packages/{quote(dataset_id, safe='/')}"
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("list_failed", f"status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RegistryError("list_failed", "invalid list response")
        return [self._release_from_dict(item) for item in items]

    def device_code(self) -> dict[str, Any]:
        status, raw, _ = self._request(
            "POST",
            "/v1/auth/github/device/code",
            body=b"{}",
            headers=self._headers(content_type="application/json", auth=False),
            auth=False,
        )
        if status != 200:
            raise RegistryError("oauth_failed", f"device code status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def device_poll(self, device_code: str) -> dict[str, Any]:
        body = json.dumps({"device_code": device_code}).encode("utf-8")
        status, raw, _ = self._request(
            "POST",
            "/v1/auth/github/device/poll",
            body=body,
            headers=self._headers(content_type="application/json", auth=False),
            auth=False,
        )
        if status == 202:
            return {"status": "authorization_pending"}
        if status != 200:
            raise RegistryError("oauth_failed", f"poll status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def upload_attempt(
        self,
        *,
        run_id: str,
        dataset_id: str,
        task_id: str,
        lock_digest: str,
        status: str,
        visibility: str,
        blob_digest: str,
        size: int,
        archive: Path,
        suite_run_id: str | None = None,
        replace: bool = False,
        environment: str | None = None,
        agent_label: str | None = None,
        model_label: str | None = None,
        score: float | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "task_id": task_id,
            "lock_digest": lock_digest,
            "status": status,
            "visibility": visibility,
            "blob_digest": blob_digest,
            "size": size,
        }
        if suite_run_id:
            meta["suite_run_id"] = suite_run_id
        if replace:
            meta["replace"] = True
        if environment:
            meta["environment"] = environment
        if agent_label:
            meta["agent_label"] = agent_label
        if model_label:
            meta["model_label"] = model_label
        if score is not None:
            meta["score"] = score
        http_status, raw, _ = self._put_multipart(
            "/v1/results/attempts",
            meta=meta,
            archive=archive,
            filename="attempt.tar.gz",
            boundary_prefix="ageval-result",
        )
        if http_status not in {200, 201}:
            raise RegistryError(
                "upload_failed", f"unexpected status {http_status}", status=http_status
            )
        return json.loads(raw.decode("utf-8"))

    def get_attempt(self, run_id: str) -> dict[str, Any]:
        path = f"/v1/results/attempts/{quote(run_id, safe='')}"
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("not_found", f"attempt not found ({status})", status=status)
        return json.loads(raw.decode("utf-8"))

    def fetch_attempt_content(self, run_id: str, dest: Path) -> Path:
        path = f"/v1/results/attempts/{quote(run_id, safe='')}/content"
        return self._download_to(path, dest)

    def list_attempts(
        self,
        *,
        dataset_id: str | None = None,
        task_id: str | None = None,
        standalone: bool = False,
    ) -> list[dict[str, Any]]:
        from urllib.parse import urlencode

        path = "/v1/results/attempts"
        query: dict[str, str] = {}
        if dataset_id:
            query["dataset_id"] = dataset_id
        if task_id:
            query["task_id"] = task_id
        if standalone:
            query["standalone"] = "1"
        if query:
            path = f"{path}?{urlencode(query)}"
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("list_failed", f"status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RegistryError("list_failed", "invalid list response")
        return [item for item in items if isinstance(item, dict)]

    def upload_suite(
        self,
        *,
        suite_run_id: str,
        dataset_id: str,
        dataset_version: str,
        visibility: str,
        pass_rate: float,
        mean_score: float,
        metrics: dict[str, Any],
        task_refs: list[dict[str, Any]],
        agent_label: str,
        model_label: str,
        exit_code: int,
        blob_digest: str,
        size: int,
        archive: Path,
        config_fingerprint: str | None = None,
        config_homogeneous: bool | None = None,
        actors_summary: list[dict[str, Any]] | None = None,
        job_overlay: dict[str, Any] | None = None,
        plugins: list[dict[str, Any]] | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "suite_run_id": suite_run_id,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "visibility": visibility,
            "pass_rate": pass_rate,
            "mean_score": mean_score,
            "metrics": metrics,
            "task_refs": task_refs,
            "agent_label": agent_label,
            "model_label": model_label,
            "exit_code": exit_code,
            "blob_digest": blob_digest,
            "size": size,
        }
        if replace:
            meta["replace"] = True
        # #42 Leaderboard comparability — thin projection from suite summary.
        if config_fingerprint is not None:
            meta["config_fingerprint"] = config_fingerprint
        if config_homogeneous is not None:
            meta["config_homogeneous"] = config_homogeneous
        if actors_summary is not None:
            meta["actors_summary"] = actors_summary
        # #59 secret-free job binding for rehydrate (locators only; never values).
        if isinstance(job_overlay, dict) and job_overlay:
            meta["job_overlay"] = job_overlay
        if isinstance(plugins, list) and plugins:
            meta["plugins"] = plugins
        http_status, raw, _ = self._put_multipart(
            "/v1/results/suites",
            meta=meta,
            archive=archive,
            filename="suite.tar.gz",
            boundary_prefix="ageval-suite",
        )
        if http_status not in {200, 201}:
            raise RegistryError(
                "upload_failed", f"unexpected status {http_status}", status=http_status
            )
        return json.loads(raw.decode("utf-8"))

    def append_suite_slot(
        self,
        *,
        suite_run_id: str,
        task_id: str,
        run_id: str,
        task_refs: list[dict[str, Any]],
        metrics: dict[str, Any],
        attempt_index: int = 0,
        pass_rate: float | None = None,
        mean_score: float | None = None,
        exit_code: int | None = None,
        config_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """PATCH one scoring slot onto an existing suite. Never uses --replace."""
        body: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "attempt_index": attempt_index,
            "task_refs": task_refs,
            "metrics": metrics,
        }
        if pass_rate is not None:
            body["pass_rate"] = pass_rate
        if mean_score is not None:
            body["mean_score"] = mean_score
        if exit_code is not None:
            body["exit_code"] = exit_code
        if config_fingerprint:
            body["config_fingerprint"] = config_fingerprint
        raw_body = json.dumps(body, sort_keys=True).encode("utf-8")
        path = f"/v1/results/suites/{quote(suite_run_id, safe='')}/slots"
        status, raw, _ = self._request(
            "POST",
            path,
            body=raw_body,
            headers=self._headers(content_type="application/json", auth=True),
            auth=True,
        )
        if status != 200:
            raise RegistryError("upload_failed", f"unexpected status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def get_suite(self, suite_run_id: str) -> dict[str, Any]:
        path = f"/v1/results/suites/{quote(suite_run_id, safe='')}"
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("not_found", f"suite not found ({status})", status=status)
        return json.loads(raw.decode("utf-8"))

    def attach_suite_agent(
        self,
        *,
        suite_run_id: str,
        agent: str,
        role: str | None = None,
    ) -> dict[str, Any]:
        """PATCH published agent_ref onto a stored suite overlay. Owner only."""
        body: dict[str, Any] = {"agent": agent}
        if role:
            body["role"] = role
        raw_body = json.dumps(body, sort_keys=True).encode("utf-8")
        path = f"/v1/results/suites/{quote(suite_run_id, safe='')}/agent-ref"
        status, raw, _ = self._request(
            "PATCH",
            path,
            body=raw_body,
            headers=self._headers(content_type="application/json", auth=True),
            auth=True,
        )
        if status != 200:
            raise RegistryError("attach_failed", f"unexpected status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def apply_request(
        self, *, kind: str, suite_run_id: str, agent: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"kind": kind, "suite_run_id": suite_run_id}
        if agent:
            body["agent"] = agent
        raw_body = json.dumps(body, sort_keys=True).encode("utf-8")
        status, raw, _ = self._request(
            "POST",
            "/v1/requests",
            body=raw_body,
            headers=self._headers(content_type="application/json", auth=True),
            auth=True,
        )
        if status != 200:
            raise RegistryError("request_failed", f"unexpected status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def list_inbox(self) -> list[dict[str, Any]]:
        status, raw, _ = self._request("GET", "/v1/requests?inbox=1", auth=True)
        if status != 200:
            raise RegistryError("list_failed", f"status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RegistryError("list_failed", "invalid list response")
        return [item for item in items if isinstance(item, dict)]

    def decide_requests(self, *, ids: list[str], action: str) -> dict[str, Any]:
        raw_body = json.dumps({"ids": ids, "action": action}, sort_keys=True).encode("utf-8")
        status, raw, _ = self._request(
            "POST",
            "/v1/requests/decide",
            body=raw_body,
            headers=self._headers(content_type="application/json", auth=True),
            auth=True,
        )
        if status != 200:
            raise RegistryError("decide_failed", f"unexpected status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def fetch_suite_content(self, suite_run_id: str, dest: Path) -> Path:
        path = f"/v1/results/suites/{quote(suite_run_id, safe='')}/content"
        return self._download_to(path, dest)

    def list_suites(
        self, *, dataset_id: str | None = None, board: bool = False
    ) -> list[dict[str, Any]]:
        from urllib.parse import urlencode

        path = "/v1/results/suites"
        q: dict[str, str] = {}
        if dataset_id:
            q["dataset_id"] = dataset_id
        if board:
            q["board"] = "1"
        if q:
            path = f"{path}?{urlencode(q)}"
        status, raw, _ = self._request("GET", path, auth=True)
        if status != 200:
            raise RegistryError("list_failed", f"status {status}", status=status)
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RegistryError("list_failed", "invalid list response")
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _release_from_dict(data: Any) -> ReleaseInfo:
        if not isinstance(data, dict):
            raise RegistryError("list_failed", "invalid release item")
        return ReleaseInfo.from_payload(data)

    # ---- orgs / shares ---------------------------------------------------

    def create_org(
        self,
        *,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        is_claimable: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "display_name": display_name or name,
            "is_claimable": is_claimable,
        }
        if description is not None:
            body["description"] = description
        status, raw, _ = self._request(
            "POST",
            "/v1/orgs",
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status not in {200, 201}:
            raise RegistryError("org_create_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def list_orgs(self) -> dict[str, Any]:
        status, raw, _ = self._request("GET", "/v1/orgs")
        if status != 200:
            raise RegistryError("org_list_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def patch_org(
        self,
        org_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if display_name is not None:
            body["display_name"] = display_name
        if description is not None:
            body["description"] = description
        status, raw, _ = self._request(
            "PATCH",
            f"/v1/orgs/{quote(org_id, safe='')}",
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("org_patch_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def patch_user(self, user_id: str, *, description: str) -> dict[str, Any]:
        status, raw, _ = self._request(
            "PATCH",
            f"/v1/users/{quote(user_id, safe='')}",
            body=json.dumps({"description": description}, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("user_patch_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def patch_package_display_name(self, dataset_id: str, *, display_name: str) -> dict[str, Any]:
        return self.patch_package(dataset_id, display_name=display_name)

    def patch_package(
        self,
        dataset_id: str,
        *,
        display_name: str | None = None,
        icon_key: str | None = None,
        icon_github: str | None = None,
    ) -> dict[str, Any]:
        path = f"/v1/packages/{quote(dataset_id, safe='/')}"
        body: dict[str, Any] = {}
        if display_name is not None:
            body["display_name"] = display_name
        if icon_key is not None:
            body["icon_key"] = icon_key
        if icon_github is not None:
            body["icon_github"] = icon_github
        status, raw, _ = self._request(
            "PATCH",
            path,
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("package_patch_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def add_org_member(self, *, org_id: str, user_id: str, role: str = "member") -> dict[str, Any]:
        body = {"user_id": user_id, "role": role}
        status, raw, _ = self._request(
            "POST",
            f"/v1/orgs/{quote(org_id, safe='')}/members",
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status not in {200, 201}:
            raise RegistryError("org_member_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def remove_org_member(self, *, org_id: str, user_id: str) -> dict[str, Any]:
        status, raw, _ = self._request(
            "DELETE",
            f"/v1/orgs/{quote(org_id, safe='')}/members/{quote(user_id, safe='')}",
        )
        if status != 200:
            raise RegistryError("org_member_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def set_org_member_role(self, *, org_id: str, user_id: str, role: str) -> dict[str, Any]:
        body = {"role": role}
        status, raw, _ = self._request(
            "PATCH",
            f"/v1/orgs/{quote(org_id, safe='')}/members/{quote(user_id, safe='')}",
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("org_member_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def transfer_org(self, *, org_id: str, user_id: str) -> dict[str, Any]:
        body = {"user_id": user_id}
        status, raw, _ = self._request(
            "POST",
            f"/v1/orgs/{quote(org_id, safe='')}/transfer",
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("org_transfer_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def share_result(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, Any]:
        body = {"target_type": target_type, "target_id": target_id}
        # result_kind is attempt|suite → attempts|suites
        kind_path = "attempts" if result_kind == "attempt" else "suites"
        path = f"/v1/results/{kind_path}/{quote(result_id, safe='')}/shares"
        status, raw, _ = self._request(
            "POST",
            path,
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status not in {200, 201}:
            raise RegistryError("share_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def unshare_result(
        self,
        *,
        result_kind: str,
        result_id: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, Any]:
        body = {"target_type": target_type, "target_id": target_id}
        kind_path = "attempts" if result_kind == "attempt" else "suites"
        path = f"/v1/results/{kind_path}/{quote(result_id, safe='')}/shares"
        status, raw, _ = self._request(
            "DELETE",
            path,
            body=json.dumps(body, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("unshare_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def delete_attempt(self, run_id: str) -> dict[str, Any]:
        path = f"/v1/results/attempts/{quote(run_id, safe='')}"
        status, raw, _ = self._request("DELETE", path)
        if status != 200:
            raise RegistryError("delete_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def delete_suite(self, suite_run_id: str, *, with_attempts: bool = False) -> dict[str, Any]:
        from urllib.parse import urlencode

        path = f"/v1/results/suites/{quote(suite_run_id, safe='')}"
        if with_attempts:
            path = f"{path}?{urlencode({'with_attempts': '1'})}"
        status, raw, _ = self._request("DELETE", path)
        if status != 200:
            raise RegistryError("delete_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def set_attempt_visibility(self, run_id: str, *, visibility: str) -> dict[str, Any]:
        if visibility not in {"public", "private"}:
            raise RegistryError("invalid_request", "visibility must be public or private")
        path = f"/v1/results/attempts/{quote(run_id, safe='')}"
        status, raw, _ = self._request(
            "PATCH",
            path,
            body=json.dumps({"visibility": visibility}, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("set_visibility_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def set_suite_visibility(self, suite_run_id: str, *, visibility: str) -> dict[str, Any]:
        if visibility not in {"public", "private"}:
            raise RegistryError("invalid_request", "visibility must be public or private")
        path = f"/v1/results/suites/{quote(suite_run_id, safe='')}"
        status, raw, _ = self._request(
            "PATCH",
            path,
            body=json.dumps({"visibility": visibility}, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("set_visibility_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def delete_package_release(self, *, dataset_id: str, version: str) -> dict[str, Any]:
        path = f"/v1/packages/{quote(dataset_id, safe='/')}/versions/{quote(version, safe='')}"
        status, raw, _ = self._request("DELETE", path)
        if status != 200:
            raise RegistryError("delete_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))

    def set_package_visibility(
        self, *, dataset_id: str, version: str, visibility: str
    ) -> dict[str, Any]:
        if visibility not in {"public", "private"}:
            raise RegistryError("invalid_request", "visibility must be public or private")
        path = f"/v1/packages/{quote(dataset_id, safe='/')}/versions/{quote(version, safe='')}"
        status, raw, _ = self._request(
            "PATCH",
            path,
            body=json.dumps({"visibility": visibility}, sort_keys=True).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
        )
        if status != 200:
            raise RegistryError("set_visibility_failed", f"status {status}", status=status)
        return json.loads(raw.decode("utf-8"))
