"""CLI: ``ageval plugin install|list|uninstall|materialize-docs``.

Install updates local cache only — never project profiles (constitution §7.5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

plugin_app = typer.Typer(
    name="plugin",
    help=(
        "Manage local mechanism plugins (ageval.plugin/1).\n\n"
        "install writes only ~/.ageval/plugins (or $AGEVAL_HOME/plugins) — "
        "it does NOT modify profiles.yaml / ageval.yaml / task.yaml. "
        "Switch bindings with profiles executor: <plugin_id>."
    ),
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    app.add_typer(plugin_app, name="plugin")


@plugin_app.command("install")
def plugin_install(
    source: Annotated[
        str,
        typer.Argument(
            help=(
                "Local path to a ageval.plugin/1 directory, or registry locator "
                "org/plugin_id@version (remote requires credentials)"
            )
        ),
    ],
) -> None:
    """Install a plugin into the local cache (never edits profiles)."""
    from ageval.config.errors import ConfigError
    from ageval.plugins.install import install_from_local
    from ageval.plugins.manifest import MANIFEST_NAMES, PluginManifestError
    from ageval.plugins.plugin_requires import PluginRequiresError
    from ageval.plugins.reserved import reject_reserved_plugin_id

    # Registry locator: contains @ and does not exist as a local path.
    src_path = Path(source)
    plugin_dir = src_path.is_dir() and any((src_path / name).is_file() for name in MANIFEST_NAMES)
    if not plugin_dir:
        try:
            reject_reserved_plugin_id(source)
        except PluginManifestError as exc:
            typer.echo(
                json.dumps({"ok": False, "error": exc.kind, "message": exc.message}),
                err=True,
            )
            raise typer.Exit(code=2) from exc
    if "@" in source and not src_path.exists():
        from ageval.application.composition import build_plugin_commands

        install_plugin_from_registry = build_plugin_commands().install_plugin_from_registry

        try:
            summary = install_plugin_from_registry(source)
        except ConfigError as exc:
            typer.echo(
                json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}),
                err=True,
            )
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(summary, sort_keys=True))
        return

    from ageval.application.composition import build_plugin_commands

    cmds = build_plugin_commands()

    def _hub_fetch(package_id: str) -> Path:
        return cmds.fetch_latest_plugin(package_id)

    try:
        result = install_from_local(src_path, hub_fetch=_hub_fetch)
    except PluginRequiresError as exc:
        typer.echo(json.dumps({"ok": False, "error": exc.kind, "message": exc.message}), err=True)
        raise typer.Exit(code=2) from exc
    except PluginManifestError as exc:
        typer.echo(json.dumps({"ok": False, "error": exc.kind, "message": exc.message}), err=True)
        raise typer.Exit(code=2) from exc
    except ConfigError as exc:
        typer.echo(
            json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}),
            err=True,
        )
        raise typer.Exit(code=2) from exc
    except OSError as exc:
        typer.echo(json.dumps({"ok": False, "error": "io_error", "message": str(exc)}), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        cmds.cleanup_plugin_tmp()
    typer.echo(json.dumps(result.as_cli_dict(), sort_keys=True))


@plugin_app.command("publish")
def plugin_publish(
    source: Annotated[Path, typer.Argument(help="Local ageval.plugin/1 package directory")],
    org: Annotated[str, typer.Option("--org", help="Organization id (required)")],
    public: Annotated[bool, typer.Option("--public", help="Publish as public")] = False,
    replace: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="Overwrite same package_id@version if org owner (default: conflict 409).",
        ),
    ] = False,
) -> None:
    """Publish a plugin package to the Registry (package_kind=plugin)."""
    from ageval.application.composition import build_plugin_commands

    publish_plugin = build_plugin_commands().publish_plugin
    from ageval.config.errors import ConfigError

    try:
        summary = publish_plugin(source, public=public, org=org, replace=replace)
    except ConfigError as exc:
        typer.echo(
            json.dumps({"ok": False, "error": exc.error_code, "message": str(exc)}),
            err=True,
        )
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(summary, sort_keys=True))


@plugin_app.command("list")
def plugin_list() -> None:
    """List installed plugins from the local index."""
    from ageval.plugins.plugin_requires import list_row_with_requires
    from ageval.plugins.store import list_installed

    rows = [list_row_with_requires(e) for e in list_installed()]
    typer.echo(json.dumps({"ok": True, "plugins": rows}, sort_keys=True))


@plugin_app.command("uninstall")
def plugin_uninstall(
    plugin_id: Annotated[str, typer.Argument(help="plugin_id to remove from cache")],
) -> None:
    """Remove a plugin from cache/index. Does not edit profiles."""
    from ageval.plugins.store import uninstall

    ok = uninstall(plugin_id)
    if not ok:
        typer.echo(
            json.dumps(
                {"ok": False, "error": "plugin_not_installed", "plugin_id": plugin_id},
            ),
            err=True,
        )
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"ok": True, "uninstalled": plugin_id}, sort_keys=True))


@plugin_app.command("materialize-docs")
def plugin_materialize_docs(
    plugin_id: Annotated[str, typer.Argument()],
    target: Annotated[
        Path,
        typer.Option("--target", help="Destination directory (explicit; no default .agents)"),
    ],
) -> None:
    """Copy plugin README/skills into *target* (never silent .agents write)."""
    from ageval.plugins.materialize import MaterializeError, materialize_docs

    try:
        copied = materialize_docs(plugin_id, target)
    except MaterializeError as exc:
        typer.echo(json.dumps({"ok": False, "error": exc.kind, "message": exc.message}), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            {"ok": True, "plugin_id": plugin_id, "target": str(target), "copied": copied},
            sort_keys=True,
        )
    )
