"""Per-file ruff ignores are a stock list. The set may shrink. It may not grow."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_STOCK = json.loads(
    (_REPO / "tests" / "architecture" / "ruff_stock.json").read_text(encoding="utf-8")
)


def _ignores() -> dict[str, list[str]]:
    doc = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    found = doc["tool"]["ruff"]["lint"]["per-file-ignores"]
    return {str(path): [str(rule) for rule in rules] for path, rules in found.items()}


def test_print_globs_stay_cli_scripts_and_tests() -> None:
    ignores = _ignores()
    assert ignores["src/ageval/cli/**"] == ["T201"]
    assert ignores["scripts/**"] == ["T201"]
    assert ignores["tests/**"] == ["T201"]
    globs = {path for path in ignores if "*" in path}
    assert globs == set(_STOCK["globs"])


def test_stock_file_ignores_do_not_grow() -> None:
    ignores = _ignores()
    stock_files: dict[str, list[str]] = _STOCK["files"]
    for path, rules in ignores.items():
        if "*" in path:
            continue
        allowed = set(stock_files.get(path, []))
        extra = sorted(set(rules) - allowed)
        assert extra == [], f"{path} added {extra}"
        assert path in stock_files
