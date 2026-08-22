"""Install a plugin from Registry into local plugins cache (Spec 04 → Spec 03)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ageval.config.errors import ConfigError
from ageval.plugins.install import install_extracted_hub
from ageval.plugins.manifest import PluginManifestError
from ageval.plugins.plugin_requires import PluginRequiresError
from ageval.plugins.reserved import reject_reserved_plugin_id
from ageval.registry.archive import extract_archive
from ageval.registry.client import RegistryError
from ageval.registry.plugin_package import PLUGIN_MEDIA_TYPE


class PluginInstallCommand:
    def __init__(self, client_factory: Any) -> None:
        self._client_factory = client_factory
        self._tmp_dirs: list[tempfile.TemporaryDirectory[str]] = []  # kept until install copies

    def install_plugin_from_registry(
        self,
        locator: str,
        *,
        registry_url: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Locator forms: ``org/plugin_id@version`` or ``org/plugin_id@sha256:…``."""
        if "@" not in locator:
            raise ConfigError(
                "invalid_ref",
                "locator must be package_id@version or package_id@sha256:…",
                location=locator,
            )
        package_id, ver_or_digest = locator.rsplit("@", 1)
        package_id = package_id.strip()
        ver_or_digest = ver_or_digest.strip()
        if not package_id or not ver_or_digest:
            raise ConfigError("invalid_ref", "empty package_id or version", location=locator)
        try:
            reject_reserved_plugin_id(package_id)
        except PluginManifestError as exc:
            raise ConfigError(exc.kind, exc.message, location=locator) from exc

        client = self._bind_client(registry_url=registry_url, token=token)
        try:
            extract_dir = self._download_plugin(
                client,
                package_id=package_id,
                version=None if ver_or_digest.startswith("sha256:") else ver_or_digest,
                package_digest=ver_or_digest if ver_or_digest.startswith("sha256:") else None,
                location=locator,
            )
            result = install_extracted_hub(
                extract_dir,
                plugin_id=package_id,
                hub_fetch=lambda pid: self.fetch_latest_plugin(
                    pid, registry_url=registry_url, token=token
                ),
            )
        except PluginRequiresError as exc:
            raise ConfigError(exc.kind, exc.message, location=locator) from exc
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        finally:
            self._cleanup_tmp()
        summary = result.as_cli_dict()
        summary["from"] = locator
        return summary

    def fetch_latest_plugin(
        self,
        package_id: str,
        *,
        registry_url: str | None = None,
        token: str | None = None,
    ) -> Path:
        """Extract the latest published plugin release of *package_id* (exact Hub id)."""
        try:
            reject_reserved_plugin_id(package_id)
        except PluginManifestError as exc:
            raise ConfigError(exc.kind, exc.message, location=package_id) from exc
        client = self._bind_client(registry_url=registry_url, token=token)
        try:
            versions = client.list_package_versions(package_id)
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        published = [row for row in versions if not row.is_draft]
        if not published:
            raise ConfigError(
                "plugin_requires_unsatisfied",
                f"no published plugin release for {package_id!r}",
                location=package_id,
            )
        latest = max(published, key=lambda row: (row.created_at, row.version))
        return self._download_plugin(
            client,
            package_id=package_id,
            version=latest.version,
            package_digest=None,
            location=package_id,
        )

    def _bind_client(
        self,
        *,
        registry_url: str | None,
        token: str | None,
    ) -> Any:
        return self._client_factory(
            registry_url=registry_url,
            token=token,
            require_token=True,
        )

    def _download_plugin(
        self,
        client: Any,
        *,
        package_id: str,
        version: str | None,
        package_digest: str | None,
        location: str,
    ) -> Path:
        try:
            if package_digest:
                meta = client.get_metadata(dataset_id=package_id, package_digest=package_digest)
            else:
                meta = client.get_metadata(dataset_id=package_id, version=version)
            if meta.media_type != PLUGIN_MEDIA_TYPE:
                raise ConfigError(
                    "invalid_package_kind",
                    f"release is not a plugin (media_type={meta.media_type})",
                    location=location,
                )
            tmp = tempfile.TemporaryDirectory(prefix="ageval-plugin-dl-")
            self._tmp_dirs.append(tmp)
            archive_path = Path(tmp.name) / "plugin.tar.gz"
            client.fetch_content(
                dataset_id=package_id,
                package_digest=meta.package_digest,
                dest=archive_path,
            )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        extract_dir = Path(tmp.name) / "pkg"
        extract_dir.mkdir()
        extract_archive(archive_path, extract_dir)
        archive_path.unlink(missing_ok=True)
        return extract_dir

    def _cleanup_tmp(self) -> None:
        while self._tmp_dirs:
            tmp = self._tmp_dirs.pop()
            tmp.cleanup()
