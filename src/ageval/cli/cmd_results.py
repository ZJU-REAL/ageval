"""CLI results upload/get/list and suite commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer


def register(app: typer.Typer) -> None:
    """Create and mount the ``results`` sub-app."""

    sub = typer.Typer(
        name="results",
        help="Upload / fetch Attempt and suite/job result bundles (results store).",
        no_args_is_help=True,
        add_completion=False,
    )

    @sub.command("upload")
    def results_upload_command(
        dataset: Annotated[
            Path,
            typer.Argument(help="Local Dataset root containing .ageval/runs/<run_id>."),
        ],
        run: Annotated[
            str,
            typer.Option("--run", help="Attempt run_id under .ageval/runs/."),
        ],
        public: Annotated[
            bool,
            typer.Option("--public", help="Create a public result (default: private)."),
        ] = False,
        replace: Annotated[
            bool,
            typer.Option(
                "--replace",
                help="Overwrite same run_id if you own it (default: conflict 409).",
            ),
        ] = False,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Upload a sealed Attempt directory to the results store."""
        from ageval.application.composition import build_results_commands

        upload_attempt_result = build_results_commands().upload_attempt_result
        from ageval.config.errors import ConfigError

        try:
            summary = upload_attempt_result(
                dataset,
                run_id=run,
                public=public,
                replace=replace,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("get")
    def results_get_command(
        run_id: Annotated[
            str,
            typer.Argument(help="Attempt run_id previously uploaded."),
        ],
        out: Annotated[
            Path,
            typer.Option("--out", help="Directory to extract the result bundle into."),
        ],
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Download and extract an Attempt result bundle."""
        from ageval.application.composition import build_results_commands

        get_attempt_result = build_results_commands().get_attempt_result
        from ageval.config.errors import ConfigError

        try:
            summary = get_attempt_result(run_id, out_dir=out, registry_url=registry_url)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("list")
    def results_list_command(
        dataset_id: Annotated[
            str | None,
            typer.Option("--dataset-id", help="Filter by dataset_id."),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """List Attempt results visible to the current credentials."""
        from ageval.application.composition import build_results_commands

        list_attempt_results = build_results_commands().list_attempt_results
        from ageval.config.errors import ConfigError

        try:
            summary = list_attempt_results(
                dataset_id=dataset_id,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("upload-suite")
    def results_upload_suite_command(
        dataset: Annotated[
            Path,
            typer.Argument(help="Local Dataset root containing .ageval/suite-runs/<id>."),
        ],
        suite_run: Annotated[
            str,
            typer.Option("--suite-run", help="Suite run id under .ageval/suite-runs/."),
        ],
        public: Annotated[
            bool,
            typer.Option("--public", help="Create a public suite result (default: private)."),
        ] = False,
        agent: Annotated[
            str,
            typer.Option("--agent", help="Optional agent label for leaderboard meta."),
        ] = "",
        model: Annotated[
            str,
            typer.Option("--model", help="Optional model label for leaderboard meta."),
        ] = "",
        with_attempts: Annotated[
            bool,
            typer.Option(
                "--with-attempts",
                help=(
                    "Also upload each local .ageval/runs/<run_id> from suite task_refs "
                    "(full Attempt evidence; optional, for Hub Jobs deep-link)."
                ),
            ),
        ] = False,
        replace: Annotated[
            bool,
            typer.Option(
                "--replace",
                help="Overwrite same suite_run_id if you own it (default: conflict 409).",
            ),
        ] = False,
        task: Annotated[
            str | None,
            typer.Option(
                "--task",
                help=(
                    "Append one local slot onto an already-uploaded suite "
                    "(current + previous[]). Not whole-row --replace."
                ),
            ),
        ] = None,
        run: Annotated[
            str | None,
            typer.Option(
                "--run",
                help="Attempt run_id to attach (default: local current for --task).",
            ),
        ] = None,
        attempt_index: Annotated[
            int,
            typer.Option(
                "--attempt-index",
                help="Always-k slot index to append (default 0). Only with --task.",
            ),
        ] = 0,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Upload a suite/job result row (metrics + task refs; no suite PASS)."""
        from ageval.application.composition import build_results_commands

        cmds = build_results_commands()
        from ageval.config.errors import ConfigError

        try:
            task_id = task.strip() if task and str(task).strip() else None
            if task_id:
                if replace:
                    raise ConfigError(
                        "invalid_request",
                        "slot append must not use --replace",
                        location="--replace",
                    )
                if attempt_index < 0:
                    raise ConfigError(
                        "invalid_override",
                        "attempt-index must be an integer ≥ 0",
                        location="--attempt-index",
                    )
                summary = cmds.append_suite_slot_result(
                    dataset,
                    suite_run_id=suite_run,
                    task_id=task_id,
                    run_id=run,
                    attempt_index=attempt_index,
                    public=public,
                    with_attempts=with_attempts,
                    registry_url=registry_url,
                )
            else:
                if run:
                    raise ConfigError(
                        "invalid_request",
                        "--run requires --task (slot append)",
                        location="--run",
                    )
                summary = cmds.upload_suite_result(
                    dataset,
                    suite_run_id=suite_run,
                    public=public,
                    agent_label=agent,
                    model_label=model,
                    with_attempts=with_attempts,
                    replace=replace,
                    registry_url=registry_url,
                )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("get-suite")
    def results_get_suite_command(
        suite_run_id: Annotated[
            str,
            typer.Argument(help="Suite run id (registry or local)."),
        ],
        out: Annotated[
            Path | None,
            typer.Option("--out", help="Optional directory to extract the suite archive into."),
        ] = None,
        local: Annotated[
            Path | None,
            typer.Option(
                "--local",
                help="Read from local Dataset .ageval/suite-runs/ (no registry).",
            ),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Get suite/job result meta; optionally extract archive from registry."""
        from ageval.application.composition import build_results_commands

        get_suite_result = build_results_commands().get_suite_result
        from ageval.config.errors import ConfigError

        try:
            summary = get_suite_result(
                suite_run_id,
                out_dir=out,
                local=local,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("export-profiles")
    def results_export_profiles_command(
        suite_run_id: Annotated[
            str,
            typer.Argument(help="Suite run id (registry or local) with job_overlay."),
        ],
        out: Annotated[
            Path,
            typer.Option(
                "--out",
                help="Write re-runnable profiles.yaml here (ageval.profiles/1).",
            ),
        ] = Path("profiles.from-suite.yaml"),
        local: Annotated[
            Path | None,
            typer.Option(
                "--local",
                help="Read from local Dataset .ageval/suite-runs/ (no registry).",
            ),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Export suite job_overlay as profiles.yaml for re-run (#59).

        Secrets are never included — only env locator names. Fill Dataset .env
        locally, then: ageval run <db> --profiles <out>.
        """
        from ageval.application.composition import build_results_commands

        export_suite_profiles = build_results_commands().export_suite_profiles
        from ageval.config.errors import ConfigError

        try:
            summary = export_suite_profiles(
                suite_run_id,
                out=out,
                local=local,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        except OSError as exc:
            typer.echo(f"invalid_package: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("list-suites")
    def results_list_suites_command(
        dataset_id: Annotated[
            str | None,
            typer.Option("--dataset-id", help="Filter by dataset_id."),
        ] = None,
        local: Annotated[
            Path | None,
            typer.Option(
                "--local",
                help="List local Dataset .ageval/suite-runs/ (no registry).",
            ),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """List suite/job results (registry or --local Dataset path)."""
        from ageval.application.composition import build_results_commands

        list_suite_results = build_results_commands().list_suite_results
        from ageval.config.errors import ConfigError

        try:
            summary = list_suite_results(
                dataset_id=dataset_id,
                local=local,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("share")
    def results_share_command(
        result_id: Annotated[
            str,
            typer.Argument(help="attempt run_id or suite_run_id."),
        ],
        kind: Annotated[
            str,
            typer.Option("--kind", help="attempt | suite"),
        ] = "attempt",
        share_org: Annotated[
            list[str] | None,
            typer.Option("--share-org", help="Share private result with org (repeatable)."),
        ] = None,
        share_user: Annotated[
            list[str] | None,
            typer.Option("--share-user", help="Share private result with user (repeatable)."),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Share a private result with org(s) and/or user(s). Owner only."""
        from ageval.application.composition import build_results_commands

        share_result = build_results_commands().share_result
        from ageval.config.errors import ConfigError

        if kind not in {"attempt", "suite"}:
            typer.echo("kind must be attempt or suite", err=True)
            raise typer.Exit(code=2)
        if not share_org and not share_user:
            typer.echo("provide --share-org and/or --share-user", err=True)
            raise typer.Exit(code=2)
        try:
            summary = share_result(
                result_kind=kind,
                result_id=result_id,
                share_orgs=share_org or [],
                share_users=share_user or [],
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("unshare")
    def results_unshare_command(
        result_id: Annotated[
            str,
            typer.Argument(help="attempt run_id or suite_run_id."),
        ],
        kind: Annotated[
            str,
            typer.Option("--kind", help="attempt | suite"),
        ] = "attempt",
        share_org: Annotated[
            list[str] | None,
            typer.Option("--share-org", help="Revoke share for org (repeatable)."),
        ] = None,
        share_user: Annotated[
            list[str] | None,
            typer.Option("--share-user", help="Revoke share for user (repeatable)."),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Revoke a private result share. Owner only."""
        from ageval.application.composition import build_results_commands

        unshare_result = build_results_commands().unshare_result
        from ageval.config.errors import ConfigError

        if kind not in {"attempt", "suite"}:
            typer.echo("kind must be attempt or suite", err=True)
            raise typer.Exit(code=2)
        if not share_org and not share_user:
            typer.echo("provide --share-org and/or --share-user", err=True)
            raise typer.Exit(code=2)
        try:
            summary = unshare_result(
                result_kind=kind,
                result_id=result_id,
                share_orgs=share_org or [],
                share_users=share_user or [],
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("delete")
    def results_delete_command(
        result_id: Annotated[
            str,
            typer.Argument(help="attempt run_id or suite_run_id."),
        ],
        kind: Annotated[
            str,
            typer.Option("--kind", help="attempt | suite"),
        ] = "attempt",
        with_attempts: Annotated[
            bool,
            typer.Option(
                "--with-attempts",
                help="When deleting a suite, also delete linked attempt results (same owner).",
            ),
        ] = False,
        yes: Annotated[
            bool,
            typer.Option("--yes", help="Confirm destructive delete (required)."),
        ] = False,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Delete an owned attempt or suite result. Requires --yes."""
        from ageval.application.composition import build_results_commands

        delete_result = build_results_commands().delete_result
        from ageval.config.errors import ConfigError

        if kind not in {"attempt", "suite"}:
            typer.echo("kind must be attempt or suite", err=True)
            raise typer.Exit(code=2)
        if not yes:
            typer.echo("refusing to delete without --yes", err=True)
            raise typer.Exit(code=2)
        try:
            summary = delete_result(
                result_kind=kind,
                result_id=result_id,
                with_attempts=with_attempts,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("set-visibility")
    def results_set_visibility_command(
        result_id: Annotated[
            str,
            typer.Argument(help="attempt run_id or suite_run_id."),
        ],
        visibility: Annotated[
            str,
            typer.Option("--visibility", help="public | private"),
        ],
        kind: Annotated[
            str,
            typer.Option("--kind", help="attempt | suite"),
        ] = "attempt",
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Set visibility of an owned attempt or suite result after upload."""
        from ageval.application.composition import build_results_commands

        set_result_visibility = build_results_commands().set_result_visibility
        from ageval.config.errors import ConfigError

        if kind not in {"attempt", "suite"}:
            typer.echo("kind must be attempt or suite", err=True)
            raise typer.Exit(code=2)
        if visibility not in {"public", "private"}:
            typer.echo("visibility must be public or private", err=True)
            raise typer.Exit(code=2)
        try:
            summary = set_result_visibility(
                result_kind=kind,
                result_id=result_id,
                visibility=visibility,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("attach-agent")
    def results_attach_agent_command(
        suite_run: Annotated[
            str,
            typer.Option("--suite-run", help="Uploaded suite_run_id on the Registry."),
        ],
        agent: Annotated[
            str,
            typer.Option(
                "--agent",
                help="Published org/name@version (optional role= prefix, like run --agent).",
            ),
        ],
        role: Annotated[
            str | None,
            typer.Option("--role", help="Attach one overlay role only."),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Stamp a published agent_ref onto a stored suite overlay after upload."""
        from ageval.application.composition import build_results_commands

        attach_suite_agent = build_results_commands().attach_suite_agent
        from ageval.config.errors import ConfigError

        try:
            summary = attach_suite_agent(
                suite_run_id=suite_run,
                agent=agent,
                role=role,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("request")
    def results_request_command(
        kind: Annotated[
            str,
            typer.Option("--kind", help="leaderboard_list | agent_appearance"),
        ],
        suite_run: Annotated[
            str,
            typer.Option("--suite-run", help="Uploaded suite_run_id."),
        ],
        agent: Annotated[
            str | None,
            typer.Option("--agent", help="Published org/name@version (appearance kind)."),
        ] = None,
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Apply for Public board listing or Agent appearance consent."""
        from ageval.application.composition import build_results_commands

        apply_request = build_results_commands().apply_request
        from ageval.config.errors import ConfigError

        try:
            summary = apply_request(
                kind=kind,
                suite_run_id=suite_run,
                agent=agent,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("inbox")
    def results_inbox_command(
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """List pending listing and appearance requests this caller can decide."""
        from ageval.application.composition import build_results_commands

        list_inbox = build_results_commands().list_inbox
        from ageval.config.errors import ConfigError

        try:
            summary = list_inbox(registry_url=registry_url)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    @sub.command("decide")
    def results_decide_command(
        request_id: Annotated[
            list[str] | None,
            typer.Option("--id", help="Request id (repeatable)."),
        ] = None,
        action: Annotated[
            str,
            typer.Option("--action", help="approve | reject"),
        ] = "approve",
        registry_url: Annotated[
            str | None,
            typer.Option("--registry-url", help="Override registry / results URL."),
        ] = None,
    ) -> None:
        """Approve or reject pending Inbox requests (same use case as Hub)."""
        from ageval.application.composition import build_results_commands

        decide_requests = build_results_commands().decide_requests
        from ageval.config.errors import ConfigError

        try:
            summary = decide_requests(
                ids=request_id or [],
                action=action,
                registry_url=registry_url,
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    app.add_typer(sub, name="results")
