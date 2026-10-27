"""CLI for re-executing retained terminal actions in a fresh environment."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit
from ageval.cli.recovery_state import resolve_keep_recovery_state


def register(app: typer.Typer) -> None:
    """Attach ``ageval replay`` to the root Typer app."""

    @app.command("replay")
    def replay_command(
        dataset: Annotated[
            Path,
            typer.Argument(help="Dataset root that holds the source Attempt."),
        ],
        run: Annotated[
            str,
            typer.Option(
                "--run", help="Source attempt id whose retained terminal actions to execute."
            ),
        ],
        evaluate: Annotated[
            bool,
            typer.Option(
                "--evaluate",
                help="Grade new artifacts with evaluator.py. Omit leaves the replay unevaluated.",
            ),
        ] = False,
        keep_recovery_state: Annotated[
            bool | None,
            typer.Option(
                "--keep-recovery-state/--no-keep-recovery-state",
                help="Retention for the new Attempt. Same flag as ageval run.",
            ),
        ] = None,
        json_out: Annotated[
            bool,
            typer.Option("--json", help="Write the replay report as JSON."),
        ] = False,
    ) -> None:
        """Execute a retained terminal action sequence in a new environment."""
        from ageval.application.composition import build_replay_attempt

        retain = resolve_keep_recovery_state(keep_recovery_state)
        code, report = asyncio.run(
            build_replay_attempt()(
                dataset,
                run,
                evaluate=evaluate,
                keep_recovery_state=retain,
            )
        )
        emit(report, json_out=json_out)
        if code != 0:
            raise typer.Exit(code=code)
