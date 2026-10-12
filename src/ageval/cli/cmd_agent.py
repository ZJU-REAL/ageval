"""CLI: ``ageval agent install|list|show|uninstall`` (design/14).

Install writes the agent cache and declared plugins — never profiles /
task.yaml. Run with ``ageval run <dataset> --agent pi`` or ``--agent <id>@<version>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ageval.cli.present import emit

agent_app = typer.Typer(
    name="agent",
    help=(
        "Manage local Agent definitions (ageval.agent/1).\n\n"
        "install writes ~/.ageval/agents (or $AGEVAL_HOME/agents) and installs "
        "plugins declared on binding.extensions[].plugin into ~/.ageval/plugins. "
        "It does NOT modify profiles.yaml / task.yaml. Bind at run time with "
        "`ageval run <dataset> --agent pi` (builtin) or `--agent <id>@<version>`."
    ),
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    app.add_typer(agent_app, name="agent")


AGENT_OPTION_HELP = (
    "Bind an Agent harness (ageval.agent/1) for this run; repeatable. "
    "Forms: short builtin id (pi, opencode, …), <id>@<version>, <role>=<ref>, "
    "or a local path to an agent dir / agent.yaml. Mutually exclusive with "
    "--profiles. binding.model is the default when --model is omitted."
)

MODEL_OPTION_HELP = (
    "Override model.id for roles bound by --agent on this lock/run/campaign. "
    "Requires --agent. Omit to keep the package default. "
    "Not the observational --model on ageval results upload / upload-suite."
)


def resolve_agent_option(
    agent: list[str] | None,
    profiles: Path | None,
    model: str | None = None,
) -> Path | None:
    """Shared --agent handling: mutual exclusion + projection into a profiles file."""
    model_text = model.strip() if isinstance(model, str) else ""
    if model is not None and not model_text:
        typer.echo("invalid_override: --model must be a non-empty string", err=True)
        raise typer.Exit(code=2)
    if model_text and not agent:
        typer.echo("invalid_override: --model requires --agent", err=True)
        raise typer.Exit(code=2)
    if not agent:
        return profiles
    if profiles is not None:
        typer.echo(
            "invalid_override: --agent and --profiles are mutually exclusive",
            err=True,
        )
        raise typer.Exit(code=2)
    from ageval.application.composition import build_agent_projection
    from ageval.config.errors import ConfigError

    try:
        return build_agent_projection()(list(agent), model=model_text or None)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


@agent_app.command("install")
def agent_install(
    source: Annotated[
        str,
        typer.Argument(
            help=(
                "Local path to a ageval.agent/1 directory, or registry locator "
                "org/agent_id@version | org/agent_id@sha256:… (remote requires credentials)"
            )
        ),
    ],
) -> None:
    """Install an agent (and its declared plugins) into the local cache."""
    from ageval.application.composition import build_agent_commands
    from ageval.config.errors import ConfigError

    cmds = build_agent_commands()
    src_path = Path(source)
    try:
        if "@" in source and not src_path.exists():
            summary = cmds.install_agent_from_registry(source)
        else:
            summary = cmds.install_agent_from_path(src_path)
    except ConfigError as exc:
        emit({"ok": False, "error": exc.error_code, "message": exc.message}, err=True)
        raise typer.Exit(code=2) from exc
    except OSError as exc:
        emit({"ok": False, "error": "io_error", "message": str(exc)}, err=True)
        raise typer.Exit(code=2) from exc
    finally:
        cmds.cleanup_agent_tmp()
    emit(summary)


@agent_app.command("publish")
def agent_publish(
    source: Annotated[Path, typer.Argument(help="Local ageval.agent/1 package directory")],
    org: Annotated[str, typer.Option("--org", help="Organization id (required)")],
    public: Annotated[bool, typer.Option("--public", help="Publish as public")] = False,
) -> None:
    """Publish an agent package to the Registry (package_kind=agent)."""
    from ageval.application.composition import build_agent_commands
    from ageval.config.errors import ConfigError

    try:
        summary = build_agent_commands().publish_agent(source, public=public, org=org)
    except ConfigError as exc:
        emit({"ok": False, "error": exc.error_code, "message": str(exc)}, err=True)
        raise typer.Exit(code=2) from exc
    emit(summary)


@agent_app.command("list")
def agent_list() -> None:
    """List installed agents from the local index."""
    from ageval.agents.store import list_installed

    rows = [e.as_dict() for e in list_installed()]
    emit({"agents": rows, "ok": True})


@agent_app.command("show")
def agent_show(
    ref: Annotated[str, typer.Argument(help="Installed id (<id> or <id>@<version>)")],
) -> None:
    """Show one installed agent's manifest (secret-free by construction)."""
    from ageval.agents.manifest import load_agent_manifest
    from ageval.agents.store import load_index, resolve_installed_ref, resolve_package_root
    from ageval.config.errors import ConfigError

    try:
        agent_id, _, version = ref.rpartition("@")
        if agent_id and version:
            entry, root = resolve_installed_ref(agent_id, version)
        else:
            entry = load_index().find(ref)
            if entry is None:
                raise ConfigError("invalid_package", f"agent not installed: {ref!r}", location=ref)
            root = resolve_package_root(entry)
        manifest = load_agent_manifest(root)
    except ConfigError as exc:
        emit({"ok": False, "error": exc.error_code, "message": str(exc)}, err=True)
        raise typer.Exit(code=2) from exc
    payload = manifest.as_dict()
    payload["ok"] = True
    payload["agent_id"] = entry.agent_id
    payload["digest"] = entry.digest
    emit(payload)


@agent_app.command("uninstall")
def agent_uninstall(
    agent_id: Annotated[
        str,
        typer.Argument(help="Installed id, or id@version to remove one version"),
    ],
) -> None:
    """Remove one version or every installed version of an id. Does not edit profiles."""
    from ageval.agents.store import uninstall

    if not uninstall(agent_id):
        emit({"agent_id": agent_id, "error": "agent_not_installed", "ok": False}, err=True)
        raise typer.Exit(code=2)
    emit({"ok": True, "uninstalled": agent_id})
