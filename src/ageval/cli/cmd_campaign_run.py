"""CLI campaign and run commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from ageval.cli.cmd_agent import AGENT_OPTION_HELP, MODEL_OPTION_HELP, resolve_agent_option
from ageval.cli.present import emit
from ageval.cli.run_output import (
    AttemptSpinner,
    RunProgress,
    dataset_label,
    dump_json,
    format_attempt_recap,
    format_duration_ms,
    format_suite_recap,
    print_human,
    use_json_stdout,
    use_progress_bar,
)


def register(app: typer.Typer) -> None:
    """Attach commands to the root Typer app."""

    @app.command("campaign")
    def campaign_command(
        package: Annotated[
            Path,
            typer.Argument(help="Dataset root (ageval.dataset/1) for campaign matrix."),
        ],
        task: Annotated[
            list[str],
            typer.Option("--task", help="Member task id; repeat for a task axis."),
        ],
        matrix: Annotated[
            list[str] | None,
            typer.Option(
                "--matrix",
                help=(
                    "Axis as /parameters/...=[json-array] or "
                    "/bindings/<role>/model|executor|options/<key>=[json-array]."
                ),
            ),
        ] = None,
        profiles: Annotated[
            Path | None,
            typer.Option(
                "--profiles",
                help="Alternate profiles.yaml replacing Dataset-root job bindings.",
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
        keep_vendor_raw: Annotated[
            bool,
            typer.Option(
                "--keep-vendor-raw",
                help=(
                    "Keep invocation vendor raw / layer B after trajectory seal. "
                    "Default: drop. Independent of --keep-workspace."
                ),
            ),
        ] = False,
    ) -> None:
        """Foreground serial campaign over a parameter matrix."""
        import asyncio

        from ageval.application.composition import build_campaign_runner
        from ageval.config.errors import ConfigError

        profiles = resolve_agent_option(agent, profiles, model=model)
        run_campaign = build_campaign_runner()
        try:
            summary = asyncio.run(
                run_campaign(
                    package,
                    list(task),
                    matrix_args=list(matrix or []),
                    profiles_path=profiles,
                    keep_vendor_raw=keep_vendor_raw,
                )
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        emit(summary)
        code = 0 if summary.get("all_pass") else 1
        raise typer.Exit(code=code)

    @app.command("run")
    def run_command(
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
                help=(
                    "Member task id (optional). Omit to run the full suite. "
                    "When set, only that member runs."
                ),
            ),
        ] = None,
        max_concurrent_tasks: Annotated[
            int | None,
            typer.Option(
                "--max-concurrent-tasks",
                help=(
                    "Max concurrent suite work units (integer ≥1). Default 1 or Dataset "
                    "defaults.max_concurrent_tasks. Speeds wall time only; does not change "
                    "n_attempts or pass/fail. Forced to 1 when a single task runs once."
                ),
            ),
        ] = None,
        n_attempts: Annotated[
            int | None,
            typer.Option(
                "--n-attempts",
                "-k",
                help=(
                    "Always-k: independent Attempts per task (integer ≥1, default 1). "
                    "CLI/job only — not a task.yaml field, not part of config_fingerprint. "
                    "Feeds pass@k / pass^k job metrics."
                ),
            ),
        ] = None,
        resume_suite: Annotated[
            str | None,
            typer.Option(
                "--resume-suite",
                help=(
                    "Resume an existing suite_run_id under .ageval/suite-runs/. "
                    "Skips finished (task_id, attempt_index) units, appends new Attempts, "
                    "recomputes pass@k / pass^k. Combine with --task to top up one task. "
                    "With --replace-slot, re-run one named finished slot instead."
                ),
            ),
        ] = None,
        replace_slot: Annotated[
            bool,
            typer.Option(
                "--replace-slot",
                help=(
                    "With --resume-suite and --task: re-run that finished slot "
                    "(PASS / FAIL / ERROR). Writes a new run_id; old row stays on "
                    "disk and in previous[]. Metrics use the new current only."
                ),
            ),
        ] = False,
        attempt_index: Annotated[
            int | None,
            typer.Option(
                "--attempt-index",
                help=(
                    "Always-k slot to replace (0-based). Default 0. Only valid with --replace-slot."
                ),
            ),
        ] = None,
        set_overrides: Annotated[
            list[str] | None,
            typer.Option(
                "--set",
                help=(
                    "Repeatable override as <JSON Pointer>=<JSON value>, e.g. "
                    '`/parameters/active_profile="solver"` or '
                    '`/bindings/solver/options/entry="pi"`. Allowlisted only.'
                ),
            ),
        ] = None,
        profiles: Annotated[
            Path | None,
            typer.Option(
                "--profiles",
                help="Alternate profiles.yaml replacing Dataset-root job bindings.",
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
        probe: Annotated[
            bool,
            typer.Option(
                "--probe",
                help=(
                    "Lock and preflight only: report whether this task could run "
                    "here. No box is opened and no Agent is invoked."
                ),
            ),
        ] = False,
        keep_workspace: Annotated[
            bool,
            typer.Option(
                "--keep-workspace",
                help=(
                    "Keep the box work root after cleanup "
                    "(default: delete; debug only — never required for Hub upload). "
                    "Docker volumes and env containers are still removed."
                ),
            ),
        ] = False,
        keep_vendor_raw: Annotated[
            bool,
            typer.Option(
                "--keep-vendor-raw",
                help=(
                    "Keep invocation vendor raw / layer B after trajectory seal "
                    "(backend_raw, request/events, evaluator_raw). Default: drop. "
                    "Independent of --keep-workspace."
                ),
            ),
        ] = False,
        json_out: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Write the full result document on stdout. Default when stdout is not a TTY."
                ),
            ),
        ] = False,
        install_dir: Annotated[
            Path | None,
            typer.Option(
                "--dir",
                help=(
                    "Parent directory for a registry ref. Looks at "
                    "<dir>/<dataset_id>/; reuses it if that child already matches, "
                    "otherwise fetches into it and runs. Relative paths are from cwd. "
                    "Requires dataset_id@version or @sha256:… (not a local path)."
                ),
            ),
        ] = None,
    ) -> None:
        """Run one member or a full Dataset suite (Application-layer task_id axis)."""
        import asyncio

        from ageval.application.composition import (
            build_dataset_checkout,
            build_probe_attempt,
            build_run_attempt,
            build_suite_runner,
        )

        profiles = resolve_agent_option(agent, profiles, model=model)
        if install_dir is not None:
            from ageval.config.errors import ConfigError as DirConfigError

            try:
                package = str(build_dataset_checkout()(package, dest=install_dir))
            except DirConfigError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=2) from exc
        if probe:
            if not task:
                typer.echo("probe requires --task", err=True)
                raise typer.Exit(code=2)
            _probe_one(build_probe_attempt(), package, task.strip(), profiles, set_overrides)
        _suite = build_suite_runner()
        execute_suite_run = _suite.execute_suite_run
        plan_suite_run = _suite.plan_suite_run
        from ageval.config.errors import ConfigError
        from ageval.config.overrides import parse_set_override

        try:
            overrides: dict[str, object] = {}
            for raw in set_overrides or ():
                pointer, value = parse_set_override(raw)
                overrides[pointer] = value

            k = n_attempts if n_attempts is not None else 1
            resume_id = resume_suite.strip() if resume_suite and str(resume_suite).strip() else None
            task_id = task.strip() if task and str(task).strip() else None
            replace_keys: set[tuple[str, int]] | None = None
            if replace_slot:
                if resume_id is None:
                    raise ConfigError(
                        "suite_replace_requires_resume",
                        "replace-slot requires --resume-suite",
                        location="--replace-slot",
                    )
                if not task_id:
                    raise ConfigError(
                        "suite_replace_requires_task",
                        "replace-slot requires --task",
                        location="--replace-slot",
                    )
                idx = 0 if attempt_index is None else attempt_index
                if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
                    raise ConfigError(
                        "invalid_override",
                        "attempt-index must be an integer ≥ 0",
                        location="--attempt-index",
                    )
                replace_keys = {(task_id, idx)}
            elif attempt_index is not None:
                raise ConfigError(
                    "invalid_override",
                    "--attempt-index is only valid with --replace-slot",
                    location="--attempt-index",
                )

            # Full suite when --task omitted; single task when provided.
            plan = plan_suite_run(
                package,
                task_id=task.strip() if task and str(task).strip() else None,
                max_concurrent_tasks=max_concurrent_tasks,
                n_attempts=k,
                suite_run_id=resume_id,
            )
            machine = use_json_stdout(force_json=json_out)
            # Historical single-task JSON only when k==1 and not resuming.
            if (
                len(plan.task_ids) == 1
                and task
                and str(task).strip()
                and plan.n_attempts == 1
                and resume_id is None
            ):
                import time

                started = time.monotonic()
                spinner = AttemptSpinner(task_id=plan.task_ids[0])
                with spinner:
                    code, result = asyncio.run(
                        build_run_attempt()(
                            package,
                            plan.task_ids[0],
                            overrides=overrides or None,
                            profiles_path=profiles,
                            keep_workspace=keep_workspace,
                            keep_vendor_raw=keep_vendor_raw,
                            on_phase=spinner.phase,
                            on_progress=spinner.stall,
                        )
                    )
                summary = result.as_dict()
                if machine:
                    dump_json(summary)
                else:
                    print_human(
                        format_attempt_recap(
                            summary,
                            task_id=plan.task_ids[0],
                            dataset_root=plan.dataset_root,
                            duration=format_duration_ms((time.monotonic() - started) * 1000.0),
                            dataset_id=plan.dataset_id,
                            dataset_version=plan.dataset_version,
                        )
                    )
                raise typer.Exit(code=code)

            import os

            from ageval.control.store import ControlStore

            # Register suite job for ageval status / ageval cancel (D4).
            control_path = Path.cwd() / ".ageval" / "control.db"
            cs = ControlStore(control_path)
            cs.put(
                plan.suite_run_id,
                status="running",
                owner="cli-run",
                payload={
                    "kind": "suite",
                    "suite_run_id": plan.suite_run_id,
                    "dataset_root": str(plan.dataset_root),
                    "pid": os.getpid(),
                    "n_attempts": plan.n_attempts,
                    "task_ids": list(plan.task_ids),
                    "max_concurrent_tasks": plan.max_concurrent_tasks,
                },
            )

            progress = RunProgress(
                suite_run_id=plan.suite_run_id,
                dataset_label=dataset_label(plan.dataset_id, plan.dataset_version),
                use_bar=use_progress_bar(),
                task_ids=list(plan.task_ids),
                n_attempts=plan.n_attempts,
            )
            try:
                suite_summary = asyncio.run(
                    execute_suite_run(
                        plan,
                        overrides=overrides or None,
                        profiles_path=profiles,
                        resume=resume_id is not None,
                        replace_slots=replace_keys,
                        on_progress=progress.handle,
                        keep_workspace=keep_workspace,
                        keep_vendor_raw=keep_vendor_raw,
                    )
                )
            finally:
                progress.close()
            final_status = (
                "cancelled"
                if suite_summary.get("cancelled")
                else ("completed" if int(suite_summary.get("exit_code", 2)) == 0 else "failed")
            )
            cs.put(
                plan.suite_run_id,
                status=final_status,
                owner="cli-run",
                payload={
                    "kind": "suite",
                    "suite_run_id": plan.suite_run_id,
                    "dataset_root": str(plan.dataset_root),
                    "exit_code": suite_summary.get("exit_code"),
                    "summary_path": suite_summary.get("summary_path"),
                    "n_attempts": plan.n_attempts,
                    "cancelled": bool(suite_summary.get("cancelled")),
                },
            )
            if machine:
                dump_json(suite_summary)
            else:
                print_human(
                    format_suite_recap(
                        suite_summary,
                        dataset_root=plan.dataset_root,
                    )
                )
            raise typer.Exit(code=int(suite_summary.get("exit_code", 2)))
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except typer.Exit:
            # Single-task path raises Exit with the real process code; do not remap to 2.
            raise
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"runtime_error: {type(exc).__name__}: {exc}", err=True)
            raise typer.Exit(code=2) from exc


def _probe_one(
    probe_attempt: Any,
    package: str,
    task: str,
    profiles: Path | None,
    set_overrides: list[str] | None,
) -> None:
    """Print the probe answer and exit: 0 when this task could run here."""
    import asyncio

    from ageval.config.errors import ConfigError
    from ageval.config.overrides import parse_set_override

    try:
        overrides = dict(parse_set_override(raw) for raw in set_overrides or ())
        answer = asyncio.run(
            probe_attempt(package, task, overrides=overrides or None, profiles_path=profiles)
        )
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    emit(answer)
    raise typer.Exit(code=0 if answer.get("ready") else 2)
