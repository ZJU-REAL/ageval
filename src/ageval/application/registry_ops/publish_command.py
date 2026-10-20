"""Application use case for ``ageval publish``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ageval.config.dataset import load_dataset_manifest
from ageval.config.errors import ConfigError
from ageval.registry.archive import MEDIA_TYPE, write_archive
from ageval.registry.client import RegistryError
from ageval.registry.digest import compute_package_digest


class PublishCommand:
    def __init__(self, client_factory: Any) -> None:
        self._client_factory = client_factory

    def publish_dataset(
        self,
        dataset_root: Path,
        *,
        public: bool = False,
        org: str | None = None,
        registry_url: str | None = None,
        token: str | None = None,
        replace: bool = False,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Validate Dataset, compute digests, publish to Registry; return summary dict.

        *replace* overwrites the same ``dataset_id@version`` for org owners only
        (blob, digests, visibility, size). Default remains conflict (409).
        *draft* writes the dataset draft slot (overwrite) instead of a release.
        """
        root = dataset_root.expanduser().resolve(strict=False)
        try:
            manifest = load_dataset_manifest(root)
        except ConfigError:
            raise

        package_digest = compute_package_digest(root)
        visibility = "public" if public else "private"
        org_id = (org or "").strip()
        if not org_id:
            raise ConfigError(
                "org_required",
                "publish requires --org (package must belong to an organization)",
                location="registry",
            )
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ageval-pub-") as tmp:
            archive_path = Path(tmp) / "package.tar.gz"
            blob_digest, size = write_archive(root, archive_path)
            client = self._client_factory(
                registry_url=registry_url,
                token=token,
                require_token=True,
            )
            try:
                info = client.publish(
                    dataset_id=manifest.dataset_id,
                    version=manifest.version,
                    package_digest=package_digest,
                    blob_digest=blob_digest,
                    size=size,
                    media_type=MEDIA_TYPE,
                    visibility=visibility,
                    archive=archive_path,
                    org_id=org_id,
                    replace=replace,
                    slot="draft" if draft else None,
                )
            except RegistryError as exc:
                raise ConfigError(exc.code, exc.message, location="registry") from exc

        out: dict[str, Any] = {
            "ok": True,
            "dataset_id": info.dataset_id,
            "version": info.version,
            "visibility": info.visibility,
            "package_digest": info.package_digest,
            "blob_digest": info.blob_digest,
            "size": info.size,
            "media_type": info.media_type,
            "ref": f"{info.dataset_id}@{info.version}",
            "digest_ref": f"{info.dataset_id}@{info.package_digest}",
            "org_id": info.org_id or org_id,
        }
        if info.replaced:
            out["replaced"] = True
        if info.is_draft:
            out["slot"] = "draft"
            out["is_draft"] = True
        return out

    def publish_from_repo(
        self,
        repo_ref: str,
        *,
        public: bool = False,
        org: str | None = None,
        registry_url: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Register a git-sourced Dataset version; no files are uploaded."""
        from ageval.config.dataset import list_tasks
        from ageval.registry.digest import compute_eval_digest
        from ageval.registry.resolve import resolve_dataset_root_with_source

        root, source = resolve_dataset_root_with_source(repo_ref)
        if source is None:  # pragma: no cover - git refs always carry source
            raise ConfigError("invalid_package", "--repo requires a git ref", location="--repo")
        manifest = load_dataset_manifest(root)
        eval_digest = compute_eval_digest(root)
        client = self._client_factory(
            registry_url=registry_url,
            token=token,
            require_token=True,
        )
        try:
            info = client.register_source(
                dataset_id=manifest.dataset_id,
                version=manifest.version,
                git_url=source["git_url"],
                commit=source["commit"],
                eval_digest=eval_digest,
                subdir=source.get("subdir"),
                org_id=(org or "").strip() or None,
                visibility="public" if public else "private",
                task_ids=list_tasks(root, manifest=manifest),
                prepare=manifest.prepare,
                assets=[{"path": a.path, "sha256": a.sha256} for a in manifest.assets],
            )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        return {
            "ok": True,
            "dataset_id": manifest.dataset_id,
            "version": manifest.version,
            "source_only": True,
            "git_url": source["git_url"],
            "commit": source["commit"],
            "eval_digest": eval_digest,
            **({"subdir": source["subdir"]} if source.get("subdir") else {}),
            "ref": f"{manifest.dataset_id}@{manifest.version}",
            "registration": info,
        }

    def release_draft(
        self,
        dataset_id: str,
        *,
        public: bool = False,
        replace: bool = False,
        version: str | None = None,
        registry_url: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Promote the current dataset draft to an immutable release."""
        db_id = (dataset_id or "").strip()
        if not db_id:
            raise ConfigError("invalid_request", "dataset_id required", location="registry")
        client = self._client_factory(
            registry_url=registry_url,
            token=token,
            require_token=True,
        )
        visibility = "public" if public else None
        try:
            info = client.release_draft(
                dataset_id=db_id,
                visibility=visibility,
                replace=replace,
                version=(version or "").strip() or None,
            )
        except RegistryError as exc:
            raise ConfigError(exc.code, exc.message, location="registry") from exc
        out: dict[str, Any] = {
            "ok": True,
            "dataset_id": info.dataset_id,
            "version": info.version,
            "visibility": info.visibility,
            "package_digest": info.package_digest,
            "blob_digest": info.blob_digest,
            "size": info.size,
            "media_type": info.media_type,
            "ref": f"{info.dataset_id}@{info.version}",
            "from_draft": True,
            "org_id": info.org_id,
        }
        if info.replaced:
            out["replaced"] = True
        return out
