"""A task's ``run.py`` imports ``lib.*`` (its own) and ``shared.*`` (the dataset's).

Both roots are on the worker's import path, and the task-local one wins when the
two ship a module with the same name.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from ageval.runtime.task_worker import load_entry

SHARED_TOKEN = "from-shared"
TASK_TOKEN = "from-task-lib"


@pytest.fixture(autouse=True)
def _isolated_imports() -> Iterator[None]:
    """The real worker is a fresh process; give each case the same clean slate."""
    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]


def _dataset(root: Path, *, with_task_lib: bool) -> tuple[Path, Path]:
    shared_lib = root / "shared" / "lib"
    shared_lib.mkdir(parents=True)
    (root / "shared" / "__init__.py").write_text("", encoding="utf-8")
    (shared_lib / "__init__.py").write_text("", encoding="utf-8")
    (shared_lib / "bridge.py").write_text(f"TOKEN = {SHARED_TOKEN!r}\n", encoding="utf-8")

    task = root / "tasks" / "t1"
    task.mkdir(parents=True)
    imports = ["from shared.lib.bridge import TOKEN as SHARED"]
    body = ["    return {'shared': SHARED}"]
    if with_task_lib:
        lib = task / "lib"
        lib.mkdir()
        (lib / "__init__.py").write_text("", encoding="utf-8")
        (lib / "bridge.py").write_text(f"TOKEN = {TASK_TOKEN!r}\n", encoding="utf-8")
        imports.append("from lib.bridge import TOKEN as TASK")
        body = ["    return {'shared': SHARED, 'task': TASK}"]
    (task / "run.py").write_text(
        "\n".join([*imports, "", "", "def run(ctx):", *body, ""]),
        encoding="utf-8",
    )
    return root, task


def test_dataset_shared_modules_are_importable(tmp_path: Path) -> None:
    dataset, task = _dataset(tmp_path / "db", with_task_lib=False)
    entry = load_entry(task, "run:run", dataset)
    assert entry(None) == {"shared": SHARED_TOKEN}


def test_task_local_lib_shadows_the_dataset_one(tmp_path: Path) -> None:
    dataset, task = _dataset(tmp_path / "db", with_task_lib=True)
    entry = load_entry(task, "run:run", dataset)
    assert entry(None) == {"shared": SHARED_TOKEN, "task": TASK_TOKEN}


def test_a_missing_entry_module_is_one_clear_error(tmp_path: Path) -> None:
    dataset, task = _dataset(tmp_path / "db", with_task_lib=False)
    with pytest.raises(FileNotFoundError, match="solve.py"):
        load_entry(task, "solve:main", dataset)


def test_an_entrypoint_without_a_function_is_rejected(tmp_path: Path) -> None:
    dataset, task = _dataset(tmp_path / "db", with_task_lib=False)
    with pytest.raises(ValueError, match="invalid entrypoint"):
        load_entry(task, "run", dataset)
