"""Suite-wide isolation. The operator home must not leak into a test."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from ageval.plugins.contrib.acp.registry import clear_registry_cache

_REQUIRE_PLUGIN_DEPS = frozenset({"1", "true", "yes", "on"})


def _plugin_deps_required() -> bool:
    raw = os.environ.get("AGEVAL_REQUIRE_PLUGIN_DEPS", "").strip().lower()
    return raw in _REQUIRE_PLUGIN_DEPS


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    """Turn a missing plugin extra into a failure when the plugins job asks for it.

    ``python-core`` installs no miniswe/nooa/dsh extra, so ``importorskip`` stays
    a skip there. ``python-plugins`` sets ``AGEVAL_REQUIRE_PLUGIN_DEPS=1``.
    """
    outcome = yield
    if not _plugin_deps_required():
        return
    report = outcome.get_result()
    if report.when not in {"setup", "call"} or not report.skipped:
        return
    detail = str(report.longrepr)
    if "could not import" not in detail.lower():
        return
    report.outcome = "failed"
    report.longrepr = "plugin dependency required (AGEVAL_REQUIRE_PLUGIN_DEPS=1): " + detail


@pytest.fixture(autouse=True)
def _isolate_ageval_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    monkeypatch.setenv("AGEVAL_HOME", str(tmp_path_factory.mktemp("ageval-home")))
    clear_registry_cache()
    yield
    clear_registry_cache()
