"""Stock ceilings. A count may fall. A new file or a higher count fails.

New ``os.environ`` reads belong in ``config/env_refs.py`` or
``runtime/offline.py``. A new ``${NAME}`` locator regex belongs in
``config/env_refs.py``. Those homes are still ceilings: growing one is a
baseline edit.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.architecture.ratchet_scan import (
    count_coded_raises,
    count_dict_any,
    count_environ,
    count_locator_regex,
    executor_plugin_gaps,
)

_CEILING = json.loads(
    (Path(__file__).resolve().parent / "ratchet_baseline.json").read_text(encoding="utf-8")
)


def _within(found: dict[str, int], key: str) -> None:
    ceiling: dict[str, int] = _CEILING[key]
    for path, count in found.items():
        assert path in ceiling, f"new {key} in {path} ({count})"
        assert count <= ceiling[path], f"{key} {path} {count} > {ceiling[path]}"


def test_os_environ_does_not_grow() -> None:
    _within(count_environ(), "os_environ")


def test_locator_regex_does_not_grow() -> None:
    _within(count_locator_regex(), "locator_regex")


def test_coded_raises_do_not_grow() -> None:
    _within(count_coded_raises(), "coded_raise")


def test_dict_any_does_not_grow() -> None:
    _within(count_dict_any(), "dict_any")


def test_executor_plugins_subclass_base_executor() -> None:
    assert executor_plugin_gaps() == []
