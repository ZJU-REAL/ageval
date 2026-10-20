"""CLI executors, publish, and login commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit


def register(app: typer.Typer) -> None:
    """Attach commands to the root Typer app."""

    @app.command("executors")
    def executors_command(
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Include capability detail (tools/session + default credential env names).",
            ),
        ] = False,
    ) -> None:
        """List supported executor kinds and host-ready / bake-declared status.

        Thin CLI: inventory logic lives in ``ageval.plugins.executor_inventory``.
        Plugin ``host_ready`` is constructability (declared host_requires /
        describe()), not install Recognition or a missing PATH binary.
        """
        from ageval.plugins.contrib.acp.registry import AcpRegistryError
        from ageval.plugins.executor_inventory import build_executor_inventory

        try:
            summary = build_executor_inventory(verbose=verbose)
        except AcpRegistryError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)

    @app.command("publish")
    def publish_command(
        dataset: Annotated[
            Path | None,
            typer.Argument(help="Local Dataset root to publish (ageval.dataset/1)."),
        ] = None,
        repo: Annotated[
            str | None,
            typer.Option(
                "--repo",
                help="Git source ref to register without upload (github:org/repo@<tag|sha>).",
            ),
        ] = None,
        org: Annotated[
            str,
            typer.Option(
                "--org",
                help="Organization id that owns this package (required for upload).",
            ),
        ] = "",
        public: Annotated[
            bool,
            typer.Option(
                "--public",
                help="Create a public release (default: private).",
            ),
        ] = False,
        replace: Annotated[
            bool,
            typer.Option(
                "--replace",
                help="Overwrite same dataset_id@version if org owner (default: conflict 409).",
            ),
        ] = False,
        draft: Annotated[
            bool,
            typer.Option(
                "--draft",
                help="Upload/overwrite the dataset draft slot instead of creating a release.",
            ),
        ] = False,
        registry_url: Annotated[
            str | None,
            typer.Option(
                "--registry-url",
                help="Override the default registry URL (AGEVAL_REGISTRY_URL / credentials).",
            ),
        ] = None,
    ) -> None:
        """Publish a local Dataset package to the configured Registry (must attach --org)."""
        from ageval.application.composition import build_publish_command
        from ageval.config.errors import ConfigError

        if bool(repo) == (dataset is not None):
            typer.echo(
                "invalid_request: pass a local Dataset root or --repo <git ref>, not both",
                err=True,
            )
            raise typer.Exit(code=2)
        try:
            if repo:
                summary = build_publish_command().publish_from_repo(
                    repo,
                    public=public,
                    org=org or None,
                    registry_url=registry_url,
                )
            else:
                assert dataset is not None
                summary = build_publish_command().publish_dataset(
                    dataset,
                    public=public,
                    org=org,
                    replace=replace,
                    draft=draft,
                    registry_url=registry_url,
                )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)

    @app.command("release")
    def release_command(
        dataset_id: Annotated[
            str,
            typer.Argument(help="Dataset id whose current draft becomes a durable release."),
        ],
        public: Annotated[
            bool,
            typer.Option(
                "--public",
                help="Publish the release as public (default: draft visibility).",
            ),
        ] = False,
        replace: Annotated[
            bool,
            typer.Option(
                "--replace",
                help="Overwrite same dataset_id@version if org owner (default: conflict 409).",
            ),
        ] = False,
        version: Annotated[
            str | None,
            typer.Option(
                "--version",
                help="Override version (default: ageval.yaml inside the draft).",
            ),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option(
                "--registry-url",
                help="Override the default registry URL (AGEVAL_REGISTRY_URL / credentials).",
            ),
        ] = None,
    ) -> None:
        """Owner: promote the current dataset draft to an immutable release."""
        from ageval.application.composition import build_publish_command
        from ageval.config.errors import ConfigError

        release_draft = build_publish_command().release_draft
        try:
            summary = release_draft(
                dataset_id,
                public=public,
                replace=replace,
                version=version,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)

    @app.command("login")
    def login_command(
        registry_url: Annotated[
            str | None,
            typer.Option(
                "--registry-url",
                help="Override the default registry URL (AGEVAL_REGISTRY_URL / credentials).",
            ),
        ] = None,
    ) -> None:
        """GitHub Device Flow login; write ``~/.ageval/credentials`` (mode 0600)."""
        from ageval.application.composition import build_login_command

        login_registry = build_login_command().login_registry
        from ageval.config.errors import ConfigError

        try:
            summary = login_registry(registry_url=registry_url)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)
