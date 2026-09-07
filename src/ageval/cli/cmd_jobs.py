"""CLI local Jobs commands (delete on-disk evidence; no Registry)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit


def register(app: typer.Typer) -> None:
    """Create and mount the ``jobs`` sub-app."""

    sub = typer.Typer(
        name="jobs",
        help="Local Jobs under a Dataset root (no Registry).",
        no_args_is_help=True,
        add_completion=False,
    )

    @sub.command("list")
    def jobs_list_command(
        dataset: Annotated[
            Path,
            typer.Argument(help="Dataset root (ageval.dataset/1) whose Jobs to list."),
        ],
    ) -> None:
        """List the Jobs already on disk under a Dataset root."""
        from ageval.application.composition import build_local_jobs_commands

        summary = build_local_jobs_commands().list_jobs(dataset)
        emit(summary)

    @sub.command("delete")
    def jobs_delete_command(
        local: Annotated[
            Path,
            typer.Option("--local", help="Local Dataset root (ageval.dataset/1)."),
        ],
        job: Annotated[
            str,
            typer.Option("--job", help="Job id: suite_run_id or unclaimed single run_id."),
        ],
        yes: Annotated[
            bool,
            typer.Option("--yes", help="Confirm destructive delete (required)."),
        ] = False,
    ) -> None:
        """Delete a local Job tree. Suite delete always cascades Attempts."""
        from ageval.application.composition import build_local_jobs_commands
        from ageval.config.errors import ConfigError

        cmds = build_local_jobs_commands()
        try:
            if not yes:
                preview = cmds.preview_delete_job(local, job_id=job)
                emit(preview)
                typer.echo("refusing to delete without --yes", err=True)
                raise typer.Exit(code=2)
            summary = cmds.delete_job(local, job_id=job, yes=True)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)

    app.add_typer(sub, name="jobs")
