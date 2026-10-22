"""CLI view, tasks, and lock commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ageval.application.composition import build_lock_command
from ageval.cli.cmd_agent import AGENT_OPTION_HELP, MODEL_OPTION_HELP
from ageval.cli.present import emit
from ageval.config.errors import ConfigError


def register(app: typer.Typer) -> None:
    """Attach commands to the root Typer app."""

    @app.command("view")
    def view_command(
        dataset: Annotated[
            str,
            typer.Argument(
                help=(
                    "Dataset root, a directory of dataset roots, or a registry ref "
                    "(<dataset_id>@<version> | <dataset_id>@sha256:<digest>)."
                ),
            ),
        ],
        host: Annotated[
            str,
            typer.Option("--host", help="Bind host (default loopback only)."),
        ] = "127.0.0.1",
        port: Annotated[
            int,
            typer.Option("--port", help="HTTP port (0 = ephemeral)."),
        ] = 8765,
        no_browser: Annotated[
            bool,
            typer.Option("--no-browser", help="Do not open a browser tab."),
        ] = False,
        dev: Annotated[
            bool,
            typer.Option(
                "--dev",
                help=(
                    "API only (no SPA bundle). Starts apps/viewer Vite when possible; "
                    "otherwise prints the two-process commands."
                ),
            ),
        ] = False,
        open_path: Annotated[
            str,
            typer.Option(
                "--open",
                help="Client path to open (e.g. /jobs/<id> or /jobs/<id>/tasks/<tid>).",
            ),
        ] = "/",
        ui_port: Annotated[
            int,
            typer.Option("--ui-port", help="Vite UI port used with --dev (default 5173)."),
        ] = 5173,
    ) -> None:
        """Open local results for one dataset, or for dataset roots in a directory."""
        from ageval.config.errors import ConfigError
        from ageval.viewer.server import serve_viewer

        try:
            serve_viewer(
                dataset,
                host=host,
                port=port,
                open_browser=not no_browser,
                block=True,
                dev=dev,
                open_path=open_path,
                ui_port=ui_port,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except FileNotFoundError as exc:
            typer.echo(f"viewer: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            # Prefer strerror / args message (serve_viewer embeds host:port on bind fail).
            detail = exc.strerror or (exc.args[1] if len(exc.args) > 1 else None) or str(exc)
            typer.echo(f"viewer: {detail}", err=True)
            raise typer.Exit(code=2) from exc

    @app.command("tasks")
    def tasks_command(
        dataset: Annotated[
            Path,
            typer.Argument(help="Path to the Dataset root directory (ageval.dataset/1)."),
        ],
        layout: Annotated[
            str,
            typer.Option(
                "--layout",
                help="Package layout. ageval (default) or harbor (task.toml task or task-set).",
            ),
        ] = "ageval",
    ) -> None:
        """List member task ids under a Dataset (fail closed on empty or id mismatch)."""
        from ageval.config.dataset import list_tasks, load_dataset_manifest
        from ageval.config.errors import ConfigError
        from ageval.config.harbor_layout import LAYOUT_HARBOR, open_harbor_root, require_layout

        try:
            chosen = require_layout(layout)
            if chosen == LAYOUT_HARBOR:
                opened = open_harbor_root(dataset)
                manifest = opened.manifest
                ids = list(opened.task_ids)
            else:
                manifest = load_dataset_manifest(dataset)
                ids = list_tasks(dataset, manifest=manifest)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc

        payload = {
            "dataset_id": manifest.dataset_id,
            "version": manifest.version,
            "tasks": ids,
            "count": len(ids),
        }
        emit(payload)

    @app.command("prepare")
    def prepare_command(
        package: Annotated[
            str,
            typer.Argument(help="Dataset root path, registry ref, or git source ref."),
        ],
        allow_prepare: Annotated[
            bool,
            typer.Option(
                "--allow-prepare",
                help="Allow running the dataset's declared prepare script.",
            ),
        ] = False,
    ) -> None:
        """Fetch declarative assets and (when allowed) run the prepare script."""
        from ageval.application.composition import build_prepare_command
        from ageval.config.errors import ConfigError

        def _notice(script: str, dataset_id: str) -> None:
            typer.echo(
                f"notice: running prepare script {script} for dataset {dataset_id}",
                err=True,
            )

        try:
            summary = build_prepare_command()(package, allow_prepare=allow_prepare, notify=_notice)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)

    @app.command("lock")
    def lock_command(
        package: Annotated[
            str,
            typer.Argument(
                help=(
                    "Dataset root path or registry ref "
                    "(<dataset_id>@<version> | <dataset_id>@sha256:<digest>)."
                ),
            ),
        ],
        task: Annotated[
            str | None,
            typer.Option(
                "--task",
                help="Member task id (required). Must match tasks/<id>/task.yaml task_id.",
            ),
        ] = None,
        set_overrides: Annotated[
            list[str] | None,
            typer.Option(
                "--set",
                help=(
                    "Repeatable override as <JSON Pointer>=<JSON value>, e.g. "
                    '`/parameters/seed=7` or `/agent_profiles/solver/model/id="x"`. '
                    "Allowlisted pointers only (intent limits are not overridable)."
                ),
            ),
        ] = None,
        profiles: Annotated[
            Path | None,
            typer.Option(
                "--profiles",
                help=(
                    "Alternate job document (ageval.profiles/1) replacing the dataset-root "
                    "profiles.yaml for this lock."
                ),
            ),
        ] = None,
        profile: Annotated[
            str | None,
            typer.Option(
                "--profile",
                help="Bind every role slot the task declares to this agent profile key.",
            ),
        ] = None,
        agent: Annotated[
            list[str] | None,
            typer.Option("--agent", help=AGENT_OPTION_HELP),
        ] = None,
        model: Annotated[
            str | None,
            typer.Option("--model", help=MODEL_OPTION_HELP),
        ] = None,
        allow_prepare: Annotated[
            bool,
            typer.Option(
                "--allow-prepare",
                help="Allow running the dataset's declared prepare script before locking.",
            ),
        ] = False,
        layout: Annotated[
            str,
            typer.Option(
                "--layout",
                help=(
                    "Package layout. ageval (default) or harbor "
                    "(unmodified Harbor task or task-set)."
                ),
            ),
        ] = "ageval",
    ) -> None:
        """Resolve a Dataset member and print a deterministic JSON summary."""
        from ageval.config.harbor_layout import LAYOUT_AGEVAL, require_layout

        try:
            chosen = require_layout(layout)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        if chosen == LAYOUT_AGEVAL and (task is None or not str(task).strip()):
            typer.echo(
                "invalid_override: --task is required "
                "(suite-wide lock without --task is not supported)",
                err=True,
            )
            raise typer.Exit(code=2)
        from ageval.cli.cmd_agent import resolve_agent_option
        from ageval.model.errors import ModelConfigError
        from ageval.plugins.errors import PluginContractError

        profiles = resolve_agent_option(agent, profiles, model=model)

        def _notice(script: str, dataset_id: str) -> None:
            typer.echo(
                f"notice: running prepare script {script} for dataset {dataset_id}",
                err=True,
            )

        try:
            summary = build_lock_command().run(
                dataset_root=package,
                task_id=task or "",
                set_overrides=set_overrides or (),
                profiles_path=profiles,
                profile=profile,
                allow_prepare=allow_prepare,
                on_prepare_script=_notice,
                layout=chosen,
                cli_task=bool(task and str(task).strip()),
            )
        except (ConfigError, ModelConfigError, PluginContractError) as exc:
            # Stable operator-facing failure: exit 2, message on stderr, empty stdout.
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc

        emit(summary)
