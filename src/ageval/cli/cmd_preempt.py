"""CLI preempt command.

Stops a running suite after the current model turn and leaves those Attempts
unsealed. Unlike ``ageval cancel``, this does not signal the controller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit


def register(app: typer.Typer) -> None:
    """Attach commands to the root Typer app."""

    @app.command("preempt")
    def preempt_command(
        run_id: Annotated[
            str,
            typer.Argument(help="suite_run_id of a running suite job."),
        ],
        store: Annotated[
            Path | None,
            typer.Option("--store", help="ControlStore sqlite path (default .ageval/control.db)."),
        ] = None,
        dataset: Annotated[
            Path | None,
            typer.Option(
                "--dataset",
                help="Dataset root. Writes suite-runs/<id>/preempt.requested.",
            ),
        ] = None,
        task: Annotated[
            list[str] | None,
            typer.Option(
                "--task",
                help=(
                    "Preempt these in-flight task ids only. Repeat for more than one. "
                    "Omit to preempt the whole suite."
                ),
            ),
        ] = None,
    ) -> None:
        """Preempt a suite job without killing its controller.

        Writes ``preempt.requested``. In-flight units stop after the current
        turn and stay unsealed. Unstarted units get the usual cancel
        placeholders. Resume with ``ageval run --resume-suite``.
        """
        from ageval.application.composition import build_suite_runner
        from ageval.control.store import ControlStore

        _suite = build_suite_runner()
        is_suite_run_locator = _suite.is_suite_run_locator
        request_suite_preempt = _suite.request_suite_preempt

        path = store or (Path.cwd() / ".ageval" / "control.db")
        cs = ControlStore(path)
        rec = cs.get(run_id)
        payload: dict = dict((rec or {}).get("payload") or {})
        kind = str(payload.get("kind") or "")
        db_root = dataset
        if db_root is None and payload.get("dataset_root"):
            db_root = Path(str(payload["dataset_root"]))
        is_suite = is_suite_run_locator(run_id, dataset_root=db_root, control_kind=kind)
        tasks = [item.strip() for item in (task or []) if isinstance(item, str) and item.strip()]

        preempt_file = None
        if is_suite and db_root is not None:
            preempt_file = str(request_suite_preempt(db_root, run_id, tasks=tasks or None))

        if not is_suite or preempt_file is None:
            emit(
                {
                    "ok": False,
                    "error": "unknown_suite",
                    "run_id": run_id,
                    "hint": "pass --dataset <root> for a suite job",
                }
            )
            raise typer.Exit(code=2)

        version = None
        if rec is not None:
            version = cs.put(
                run_id,
                status=str(rec.get("status") or "running"),
                owner=str(rec.get("owner") or "cli"),
                payload={
                    **payload,
                    "kind": "suite",
                    "preempt_requested": True,
                    "preempt_file": preempt_file,
                    "preempt_tasks": tasks,
                },
            )
        emit(
            {
                "ok": True,
                "run_id": run_id,
                "status": "preempt_requested",
                "kind": "suite",
                "version": version,
                "preempt_file": preempt_file,
                "tasks": tasks,
            }
        )
