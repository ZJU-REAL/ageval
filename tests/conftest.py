"""Suite-wide isolation. The operator home must not leak into a test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ageval.plugins.contrib.acp.registry import clear_registry_cache


@pytest.fixture(autouse=True)
def _isolate_ageval_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    monkeypatch.setenv("AGEVAL_HOME", str(tmp_path_factory.mktemp("ageval-home")))
    clear_registry_cache()
    yield
    clear_registry_cache()
