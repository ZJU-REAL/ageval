"""Production composition root.

Every concrete adapter the public CLI needs is wired here and nowhere else.
Domain modules must not construct platform objects or global singletons at
import time, and the CLI must not import anything but this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ageval.application.lock import LockCommand
from ageval.config.capabilities import DeclarationCapabilityCatalog
from ageval.config.load_and_lock import ConfigCore
from ageval.config.package_fs import LocalPackageReader


def build_config_core() -> ConfigCore:
    """Assemble Config Core with the production package reader."""
    return ConfigCore(package_reader=LocalPackageReader())


def build_declaration_catalog() -> DeclarationCapabilityCatalog:
    """Declaration-only catalog used at lock time.

    A positive answer means "Config recognizes this declaration", never "the
    adapter is implemented and ready".
    """
    return DeclarationCapabilityCatalog()


def build_lock_command() -> LockCommand:
    """Wire the production ``ageval lock`` use case."""
    return LockCommand(
        config_core=build_config_core(),
        capabilities=build_declaration_catalog(),
    )


def build_override_parser() -> Callable[[list[str]], dict[str, Any]]:
    """Parse ``--set`` rows into an allowlisted pointer → value mapping."""
    from ageval.config.overrides import parse_set_override

    def _parse(rows: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for row in rows:
            pointer, value = parse_set_override(row)
            out[pointer] = value
        return out

    return _parse


def build_run_attempt() -> Callable[..., Any]:
    """Wire the production ``ageval run`` use case (one foreground Attempt)."""
    from ageval.application.run import run_attempt

    return run_attempt


def build_probe_attempt() -> Callable[..., Any]:
    """Wire ``ageval run --probe``: lock plus preflight, and nothing else."""
    from ageval.application.run import probe_attempt

    return probe_attempt


def build_campaign_runner() -> Callable[..., Any]:
    """Wire the production ``ageval campaign`` use case."""
    from ageval.application.campaign import run_campaign

    return run_campaign


def build_suite_runner() -> Any:
    """Suite plan / execute / cancel / locator helpers."""
    from ageval.application.suite import suite_run

    return suite_run


def build_results_commands() -> Any:
    """Attempt and suite result upload / get / list / share / delete / attach / inbox."""
    from ageval.application.registry_ops.results_command import ResultsCommands

    return ResultsCommands(client_factory=build_registry_client)


def build_local_jobs_commands() -> Any:
    """Local Job delete for Viewer / ``ageval jobs delete`` (no Registry)."""
    from ageval.application.local_jobs import LocalJobsCommands

    return LocalJobsCommands()


def build_registry_list_commands() -> Any:
    """Package list/show/delete/visibility and local cache helpers."""
    from ageval.application.registry_ops.registry_list_command import RegistryListCommands

    return RegistryListCommands(client_factory=build_registry_client)


def build_registry_org_commands() -> Any:
    """Org create / list / add-member / remove-member."""
    from ageval.application.registry_ops.registry_org_command import RegistryOrgCommands

    return RegistryOrgCommands(client_factory=build_registry_client)


def build_publish_command() -> Any:
    from ageval.application.registry_ops.publish_command import PublishCommand

    return PublishCommand(client_factory=build_registry_client)


def build_login_command() -> Any:
    from ageval.application.registry_ops.login_command import LoginCommand

    return LoginCommand(client_factory=build_registry_client)


def build_plugin_commands() -> Any:
    from ageval.application.plugin_ops.plugin_install_remote import PluginInstallCommand
    from ageval.application.plugin_ops.plugin_publish import PluginPublishCommand

    install = PluginInstallCommand(client_factory=build_registry_client)
    publish = PluginPublishCommand(client_factory=build_registry_client)
    return type(
        "PluginCommands",
        (),
        {
            "install_plugin_from_registry": install.install_plugin_from_registry,
            "fetch_latest_plugin": install.fetch_latest_plugin,
            "cleanup_plugin_tmp": install._cleanup_tmp,
            "publish_plugin": publish.publish_plugin,
        },
    )()


def build_agent_projection() -> Callable[[list[str]], Any]:
    """``--agent`` specs → synthesized job document path."""
    from ageval.application.agent_ops.resolve import resolve_agent_specs

    return resolve_agent_specs


def build_agent_commands() -> Any:
    from ageval.application.agent_ops.install_remote import AgentInstallCommand
    from ageval.application.agent_ops.publish import AgentPublishCommand

    install = AgentInstallCommand(client_factory=build_registry_client)
    publish = AgentPublishCommand(client_factory=build_registry_client)
    return type(
        "AgentCommands",
        (),
        {
            "install_agent_from_registry": install.install_agent_from_registry,
            "cleanup_agent_tmp": install.cleanup_tmp,
            "publish_agent": publish.publish_agent,
        },
    )()


def build_registry_client(
    *,
    registry_url: str | None = None,
    token: str | None = None,
    require_token: bool = True,
    accept_results_url: bool = False,
) -> Any:
    from ageval.application.registry_ops.client import build_registry_client as _build

    return _build(
        registry_url=registry_url,
        token=token,
        require_token=require_token,
        accept_results_url=accept_results_url,
    )
