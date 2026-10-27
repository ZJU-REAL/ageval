"""CLI listing of retained Attempt checkpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit


def register(app: typer.Typer) -> None:
    """Attach ``ageval checkpoints`` to the root Typer app."""

    @app.command("checkpoints")
    def checkpoints_command(
        dataset: Annotated[
            Path,
            typer.Argument(help="Dataset root that holds .ageval/runs/<attempt_id>."),
        ],
        run: Annotated[
            str,
            typer.Option("--run", help="Source attempt id whose recovery bundle to list."),
        ],
        json_out: Annotated[
            bool,
            typer.Option("--json", help="Write the checkpoint listing as JSON."),
        ] = False,
    ) -> None:
        """List retained checkpoints and whether each cut can start a fork."""
        from ageval.application.composition import build_list_checkpoints

        listing = build_list_checkpoints()(dataset, run)
        emit(listing.as_dict(), json_out=json_out)
        if listing.error is not None:
            raise typer.Exit(code=2)
