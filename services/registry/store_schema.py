"""The one place that bootstraps the Registry metadata schema.

``open_stores`` runs it once per database; aggregate stores never create
tables themselves. ``api_tokens`` stays owned by ``PersistentTokenStore``
(the one statement group skipped here).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.registry import queries as Q
from services.registry.store_inbox import InboxStore
from services.registry.store_org import OrgStore
from services.registry.store_package import PackageStore
from services.registry.store_result import ResultStore


def init_schema(adapter: Any) -> None:
    with adapter.connect() as conn:
        adapter.lock_schema(conn)
        for stmt in Q.SCHEMA_STATEMENTS:
            if "api_tokens" in stmt:
                continue
            adapter.execute(conn, stmt)
        for table, column, decl in Q.SCHEMA_MIGRATIONS:
            adapter.add_column(conn, table, column, decl)
        for table, column in Q.SCHEMA_INTEGER_FLAGS:
            adapter.align_integer_flag(conn, table, column)
        conn.commit()


@dataclass(frozen=True, slots=True)
class RegistryStores:
    """The four aggregate stores sharing one dialect adapter."""

    packages: PackageStore
    results: ResultStore
    orgs: OrgStore
    inbox: InboxStore


def open_stores(*, db_path: Path | None = None, adapter: Any | None = None) -> RegistryStores:
    from services.registry.sql_adapter import SqliteAdapter

    if adapter is None:
        if db_path is None:
            raise TypeError("open_stores requires db_path or adapter")
        adapter = SqliteAdapter(db_path)
    init_schema(adapter)
    return RegistryStores(
        packages=PackageStore(adapter),
        results=ResultStore(adapter),
        orgs=OrgStore(adapter),
        inbox=InboxStore(adapter),
    )


def open_sqlite_stores(db_path: Path) -> RegistryStores:
    """Test / local factory: four aggregate stores over one SQLite file."""
    return open_stores(db_path=db_path)
