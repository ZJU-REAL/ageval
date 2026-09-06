"""CLI evidence export and status commands."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit


def register(app: typer.Typer) -> None:
    """Attach commands to the root Typer app."""

    @app.command("evidence")
    def evidence_export_command(
        evidence_root: Annotated[
            Path,
            typer.Argument(help="Attempt evidence root (Result.logs path)."),
        ],
        out: Annotated[
            Path,
            typer.Option("--out", help="Destination directory for versioned export."),
        ],
    ) -> None:
        """Export sealed trajectory as a re-redacted copy. Does not change score."""
        from ageval.evidence.export import export_trajectory

        result = export_trajectory(evidence_root, out)
        emit(
            {
                "ok": result.ok,
                "export_path": result.export_path,
                "invocation_count": result.invocation_count,
                "error": result.error,
                "schema": "ageval.trajectory.export/1",
            }
        )
        raise typer.Exit(code=0 if result.ok else 2)

    @app.command("status")
    def status_command(
        run_id: Annotated[
            str,
            typer.Argument(help="Run id or suite_run_id from ControlStore / ageval run."),
        ],
        store: Annotated[
            Path | None,
            typer.Option("--store", help="ControlStore sqlite path (default .ageval/control.db)."),
        ] = None,
        dataset: Annotated[
            Path | None,
            typer.Option(
                "--dataset",
                help="Dataset root to also load suite progress.json when kind=suite.",
            ),
        ] = None,
    ) -> None:
        """Query durable Run/suite control record (+ suite progress when available)."""
        import json as _json

        from ageval.application.composition import build_suite_runner

        is_suite_run_locator = build_suite_runner().is_suite_run_locator
        from ageval.control.store import ControlStore

        path = store or (Path.cwd() / ".ageval" / "control.db")
        rec = ControlStore(path).get(run_id)
        payload = dict((rec or {}).get("payload") or {})
        kind = str(payload.get("kind") or "")
        db_root = dataset
        if db_root is None and payload.get("dataset_root"):
            db_root = Path(str(payload["dataset_root"]))
        is_suite = is_suite_run_locator(run_id, dataset_root=db_root, control_kind=kind)
        if rec is None and not is_suite:
            emit({"ok": False, "error": "unknown_run", "run_id": run_id})
            raise typer.Exit(code=2)

        out: dict = {"ok": True, "run_id": run_id}
        if rec is not None:
            out.update(rec)
        if db_root is not None and is_suite:
            from ageval.application.suite.document import suite_dir

            prog = suite_dir(db_root.expanduser().resolve(strict=False), run_id) / "progress.json"
            if prog.is_file():
                with contextlib.suppress(OSError, ValueError, TypeError):
                    data = _json.loads(prog.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        out["progress"] = data
            cancel_p = prog.parent / "cancel.requested"
            out["cancel_requested"] = cancel_p.is_file()
        if rec is None and "progress" not in out and not (db_root is not None and is_suite):
            emit({"ok": False, "error": "unknown_run", "run_id": run_id})
            raise typer.Exit(code=2)
        emit(out)
