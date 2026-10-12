"""Builtin plugins load from explicit module tuples, not a directory scan."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from ageval.plugins import builtin
from ageval.plugins.builtin import load_builtin_environments, load_builtin_executors
from ageval.plugins.registry import ExtensionRegistry
from ageval.plugins.slots import AFTER_ENVIRONMENT_READY, ENVIRONMENT, EXECUTOR, TRAJECTORY_COLLECT

_ENVIRONMENT_MODULES = (
    "ageval.plugins.contrib.local.host",
    "ageval.plugins.contrib.docker.host",
    "ageval.plugins.contrib.e2b.host",
    "ageval.plugins.contrib.daytona.host",
    "ageval.plugins.contrib.ssh.host",
)
_EXECUTOR_MODULES = (
    "ageval.plugins.contrib.acp.executor",
    "ageval.plugins.contrib.openai_http.executor",
    "ageval.plugins.contrib.anthropic_http.executor",
)


def test_builtin_module_tuples_are_the_authoritative_membership() -> None:
    assert builtin._BUILTIN_ENVIRONMENT_MODULES == _ENVIRONMENT_MODULES
    assert builtin._BUILTIN_EXECUTOR_MODULES == _EXECUTOR_MODULES
    assert "miniswe" not in "".join(builtin._BUILTIN_EXECUTOR_MODULES)
    assert "miniswe" not in "".join(builtin._BUILTIN_ENVIRONMENT_MODULES)
    assert "miniswe" not in "".join(builtin._EXECUTOR_REGISTRARS)
    assert set(builtin._ENVIRONMENT_REGISTRARS) >= set(builtin._BUILTIN_ENVIRONMENT_MODULES)
    assert set(builtin._EXECUTOR_REGISTRARS) >= set(builtin._BUILTIN_EXECUTOR_MODULES)


def test_load_registers_todays_contrib_factories() -> None:
    from ageval.plugins.contrib.acp.executor import AcpExecutor
    from ageval.plugins.contrib.anthropic_http.executor import AnthropicHTTPExecutor
    from ageval.plugins.contrib.daytona.host import DaytonaHost
    from ageval.plugins.contrib.docker.host import DockerHost
    from ageval.plugins.contrib.e2b.host import E2BHost
    from ageval.plugins.contrib.local.host import LocalHost
    from ageval.plugins.contrib.openai_http.executor import OpenAIHTTPExecutor
    from ageval.plugins.contrib.ssh.host import SSHHost

    reg = ExtensionRegistry()
    load_builtin_environments(reg)
    load_builtin_executors(reg)

    factories = {
        (ENVIRONMENT, "local"): LocalHost,
        (ENVIRONMENT, "docker"): DockerHost,
        (ENVIRONMENT, "e2b"): E2BHost,
        (ENVIRONMENT, "daytona"): DaytonaHost,
        (ENVIRONMENT, "ssh"): SSHHost,
        (EXECUTOR, "acp"): AcpExecutor,
        (EXECUTOR, "openai-http"): OpenAIHTTPExecutor,
        (EXECUTOR, "anthropic-http"): AnthropicHTTPExecutor,
    }
    for (slot, plugin_id), impl in factories.items():
        row = reg.get_registration(slot, plugin_id)
        assert row is not None
        assert row.impl is impl
        assert row.source == "first-party"
    openai = reg.get_registration(EXECUTOR, "openai-http")
    acp = reg.get_registration(EXECUTOR, "acp")
    assert openai is not None and openai.priority == 120
    assert acp is not None and acp.priority == 100
    assert "acp" in reg.plugins_for_slot(AFTER_ENVIRONMENT_READY)
    assert "acp" in reg.plugins_for_slot(TRAJECTORY_COLLECT)
    injects = reg.injects_for_plugin("acp")
    assert len(injects) == 1
    assert injects[0].service == ENVIRONMENT
    assert "attach_stdio" in injects[0].capabilities
    assert "miniswe" not in reg.plugins_for_slot(EXECUTOR)


def test_removing_one_environment_entry_skips_that_contrib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dropped = "ageval.plugins.contrib.ssh.host"
    monkeypatch.setattr(
        builtin,
        "_BUILTIN_ENVIRONMENT_MODULES",
        tuple(name for name in builtin._BUILTIN_ENVIRONMENT_MODULES if name != dropped),
    )
    imported: list[str] = []
    real_import = importlib.import_module

    def spy(name: str, package: str | None = None) -> object:
        imported.append(name)
        return real_import(name, package)

    monkeypatch.setattr(builtin.importlib, "import_module", spy)
    reg = ExtensionRegistry()
    load_builtin_environments(reg)

    assert dropped not in imported
    assert "ageval.plugins.contrib.ssh" not in imported
    assert "ssh" not in reg.plugins_for_slot(ENVIRONMENT)
    for plugin_id in ("local", "docker", "e2b", "daytona"):
        assert plugin_id in reg.plugins_for_slot(ENVIRONMENT)


def test_removing_one_executor_entry_skips_that_contrib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dropped = "ageval.plugins.contrib.openai_http.executor"
    monkeypatch.setattr(
        builtin,
        "_BUILTIN_EXECUTOR_MODULES",
        tuple(name for name in builtin._BUILTIN_EXECUTOR_MODULES if name != dropped),
    )
    imported: list[str] = []
    real_import = importlib.import_module

    def spy(name: str, package: str | None = None) -> object:
        imported.append(name)
        return real_import(name, package)

    monkeypatch.setattr(builtin.importlib, "import_module", spy)
    reg = ExtensionRegistry()
    load_builtin_executors(reg)

    assert dropped not in imported
    assert "openai-http" not in reg.plugins_for_slot(EXECUTOR)
    assert "acp" in reg.plugins_for_slot(EXECUTOR)
    assert "anthropic-http" in reg.plugins_for_slot(EXECUTOR)
    assert "acp" in reg.plugins_for_slot(AFTER_ENVIRONMENT_READY)


def test_listed_class_factory_is_kept_and_acp_companions_still_register() -> None:
    class AcpKept:
        kind = "acp"

    AcpKept.__module__ = "ageval.plugins.contrib.acp.executor"
    reg = ExtensionRegistry()
    reg.exclusive(EXECUTOR, "acp", AcpKept, priority=77, source="first-party", is_factory=True)
    load_builtin_executors(reg)

    row = reg.get_registration(EXECUTOR, "acp")
    assert row is not None
    assert row.impl is AcpKept
    assert row.priority == 77
    assert "acp" in reg.plugins_for_slot(AFTER_ENVIRONMENT_READY)
    assert "acp" in reg.plugins_for_slot(TRAJECTORY_COLLECT)
    assert reg.injects_for_plugin("acp")[0].service == ENVIRONMENT
    assert reg.get_registration(EXECUTOR, "openai-http") is not None


def test_loader_does_not_scan_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("builtin loader scanned the filesystem")

    monkeypatch.setattr(pkgutil, "iter_modules", boom)
    reg = ExtensionRegistry()
    load_builtin_environments(reg)
    load_builtin_executors(reg)
    assert "local" in reg.plugins_for_slot(ENVIRONMENT)
    assert "acp" in reg.plugins_for_slot(EXECUTOR)


def test_miniswe_arrives_only_via_load_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGEVAL_HOME", str(home))
    package = tmp_path / "miniswe-probe"
    source = package / "src" / "miniswe_probe"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "factory.py").write_text(
        "def build_executor(**kwargs):\n    return kwargs\n",
        encoding="utf-8",
    )
    (package / "plugin.yaml").write_text(
        "format: ageval.plugin/1\n"
        "plugin_id: miniswe\n"
        "version: 0.1.0\n"
        "description: probe that miniswe is installed, not builtin\n"
        "slots:\n"
        "  exclusive:\n"
        "    - id: executor\n"
        "      entry: miniswe_probe.factory:build_executor\n",
        encoding="utf-8",
    )
    from ageval.plugins.bootstrap import bootstrap_registry
    from ageval.plugins.store import install_from_path

    builtin_only = ExtensionRegistry()
    load_builtin_executors(builtin_only)
    assert "miniswe" not in builtin_only.plugins_for_slot(EXECUTOR)

    install_from_path(package)
    loaded = bootstrap_registry(ExtensionRegistry())
    assert "miniswe" in loaded.plugins_for_slot(EXECUTOR)
    assert "acp" in loaded.plugins_for_slot(EXECUTOR)
    assert "local" in loaded.plugins_for_slot(ENVIRONMENT)
