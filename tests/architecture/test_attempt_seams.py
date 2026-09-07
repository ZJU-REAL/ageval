"""Attempt seams: one identity, visible phases, cleanup that cannot be skipped."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "ageval"
ATTEMPT = SRC / "attempt"


def test_attempt_module_names_every_phase_in_order() -> None:
    """Rule: opening attempt/__init__.py is enough to say what happens when."""
    text = (ATTEMPT / "__init__.py").read_text(encoding="utf-8")
    order = [
        text.index("environment.run"),
        text.index("run.run"),
        text.index("evaluate.run"),
        text.index("record.run"),
        text.index("cleanup.run"),
    ]
    assert order == sorted(order)
    for name in ("environment", "run", "evaluate", "record", "cleanup"):
        assert (ATTEMPT / "phases" / f"{name}.py").is_file(), name


def test_cleanup_runs_in_a_finally() -> None:
    tree = ast.parse((ATTEMPT / "__init__.py").read_text(encoding="utf-8"))
    finallies = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for node in node.finalbody
    ]
    assert any("cleanup.run" in body for body in finallies)


def test_cleanup_phase_really_stops_the_box() -> None:
    text = (ATTEMPT / "phases" / "cleanup.py").read_text(encoding="utf-8")
    assert "host.stop" in text
    assert "cleanup_warning" in text, "a failed teardown must be reported, not swallowed"


def test_verdict_enters_only_through_bind_evaluation() -> None:
    binders = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if "bind_evaluation(" in path.read_text(encoding="utf-8")
    ]
    assert sorted(str(p) for p in binders) == [
        "attempt/ctx.py",
        "attempt/phases/evaluate.py",
    ]


def test_one_attempt_mints_one_run_in_source() -> None:
    text = (SRC / "application" / "run.py").read_text(encoding="utf-8")
    assert text.count(".new_run(") == 1


def test_only_one_place_constructs_an_exclusive_winner() -> None:
    callers = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if "registration.impl(" in path.read_text(encoding="utf-8")
    ]
    assert [str(p) for p in callers] == ["plugins/binding.py"]


def test_cli_imports_only_composition() -> None:
    cli = SRC / "cli"
    offenders: list[str] = []
    for path in cli.glob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "ageval.application." not in stripped:
                continue
            if "ageval.application.composition" in stripped:
                continue
            offenders.append(f"{path.name}:{i}:{stripped}")
    assert offenders == []


def test_ageval_runs_layout_owned_by_evidence() -> None:
    offenders: list[str] = []
    needle = '/ ".ageval" / "runs"'
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if rel.parts[0] == "evidence":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if needle in s or s.replace("'", '"').find('/ ".ageval" / "runs"') >= 0:
                offenders.append(f"{rel}:{i}:{s}")
    assert offenders == []


def test_queries_own_single_releases_ddl() -> None:
    queries = (REPO / "services" / "registry" / "queries.py").read_text(encoding="utf-8")
    assert queries.count("CREATE TABLE IF NOT EXISTS releases") == 1
    adapter = (REPO / "services" / "registry" / "sql_adapter.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS releases" not in adapter


def test_handler_calls_all_domain_services() -> None:
    api = (REPO / "services" / "registry" / "http_api.py").read_text(encoding="utf-8")
    for needle in ("state.packages.", "state.results.", "state.orgs.", "state.auth."):
        assert needle in api, needle


def test_handler_methods_do_not_touch_store() -> None:
    text = (REPO / "services" / "registry" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    handler = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "make_handler":
            handler = next(
                (n for n in ast.walk(node) if isinstance(n, ast.ClassDef) and n.name == "Handler"),
                None,
            )
            break
    assert handler is not None
    src = ast.get_source_segment(text, handler) or ""
    assert "state.meta." not in src
    assert "state.blobs." not in src
    assert "state.stores." not in src


def test_bearer_is_only_used_by_dispatch() -> None:
    text = (REPO / "services" / "registry" / "http_api.py").read_text(encoding="utf-8")
    assert text.count("_bearer(") == 2


def test_store_has_no_sql_literals() -> None:
    needles = ("DELETE FROM", "INSERT INTO", "CREATE TABLE", "UPDATE ")
    offenders: list[str] = []
    store_files = sorted((REPO / "services" / "registry").glob("store*.py"))
    assert {p.name for p in store_files} >= {
        "store.py",
        "store_package.py",
        "store_result.py",
        "store_org.py",
        "store_inbox.py",
        "store_schema.py",
    }
    for path in store_files:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(n in line for n in needles):
                offenders.append(f"{path.name}:{i}:{stripped}")
    assert offenders == []


def test_registry_ops_have_no_private_client_helpers() -> None:
    root = SRC / "application" / "registry_ops"
    for path in root.glob("*_command.py"):
        text = path.read_text(encoding="utf-8")
        assert "def _client(" not in text, path.name
        if path.name != "client.py":
            assert "RegistryClient(" not in text, path.name
    results = (root / "results_command.py").read_text(encoding="utf-8")
    assert "suite.suite_metrics" not in results
