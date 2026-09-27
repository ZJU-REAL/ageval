"""The one place that bootstraps the Registry metadata schema.

``open_stores`` runs it once per database; aggregate stores never create
tables themselves. ``api_tokens`` is created by ``PersistentTokenStore``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.registry.orgs import queries as org_queries
from services.registry.packages import queries as package_queries
from services.registry.results import queries as result_queries
from services.registry.shares import queries as share_queries
from services.registry.inbox import queries as inbox_queries
from services.registry.inbox.store import InboxStore
from services.registry.orgs.store import OrgStore
from services.registry.packages.store import PackageStore
from services.registry.results.store import ResultStore
from services.registry.shares.store import ShareStore


def init_schema(adapter: Any) -> None:
    with adapter.connect() as conn:
        adapter.lock_schema(conn)
        for stmt in (
            *org_queries.SCHEMA_STATEMENTS,
            *package_queries.SCHEMA_STATEMENTS,
            *result_queries.SCHEMA_STATEMENTS,
            *share_queries.SCHEMA_STATEMENTS,
            *inbox_queries.SCHEMA_STATEMENTS,
        ):
            adapter.execute(conn, stmt)
        for table, column, decl in (
            *org_queries.SCHEMA_MIGRATIONS,
            *package_queries.SCHEMA_MIGRATIONS,
            *result_queries.SCHEMA_MIGRATIONS,
            *share_queries.SCHEMA_MIGRATIONS,
            *inbox_queries.SCHEMA_MIGRATIONS,
        ):
            adapter.add_column(conn, table, column, decl)
        for table, column in (
            *org_queries.SCHEMA_INTEGER_FLAGS,
            *package_queries.SCHEMA_INTEGER_FLAGS,
            *result_queries.SCHEMA_INTEGER_FLAGS,
        ):
            adapter.align_integer_flag(conn, table, column)
        conn.commit()


@dataclass(frozen=True, slots=True)
class RegistryStores:
    """The five aggregate stores sharing one dialect adapter."""

    packages: PackageStore
    results: ResultStore
    shares: ShareStore
    orgs: OrgStore
    inbox: InboxStore


def open_stores(*, db_path: Path | None = None, adapter: Any | None = None) -> RegistryStores:
    from services.registry.db.sql_adapter import SqliteAdapter

    if adapter is None:
        if db_path is None:
            raise TypeError("open_stores requires db_path or adapter")
        adapter = SqliteAdapter(db_path)
    init_schema(adapter)
    return RegistryStores(
        packages=PackageStore(adapter),
        results=ResultStore(adapter),
        shares=ShareStore(adapter),
        orgs=OrgStore(adapter),
        inbox=InboxStore(adapter),
    )


def open_sqlite_stores(db_path: Path) -> RegistryStores:
    """Test / local factory: five aggregate stores over one SQLite file."""
    return open_stores(db_path=db_path)
