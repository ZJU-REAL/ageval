"""Dialect placeholder translation + shared query builders."""

from __future__ import annotations

from services.registry import queries as Q
from services.registry.dialect import pg_sql
from services.registry.routes import match_route


def test_pg_sql_translates_placeholders() -> None:
    assert pg_sql("SELECT * FROM t WHERE a=? AND b=?") == "SELECT * FROM t WHERE a=%s AND b=%s"
    assert "?" not in pg_sql(Q.INSERT_RELEASE)


def test_list_releases_query_public_default() -> None:
    sql, params = Q.list_releases_query()
    assert "visibility = 'public'" in sql
    assert params == []


def test_list_releases_query_private_filter() -> None:
    sql, params = Q.list_releases_query(include_private=True, visibility="private")
    assert "visibility = ?" in sql
    assert params == ["private"]
    assert "visibility = %s" in pg_sql(sql)


def test_match_route_release_draft() -> None:
    matched = match_route("POST", "/v1/packages/acme/db/release")
    assert matched is not None
    route, kwargs = matched
    assert route.name == "release_draft"
    assert kwargs["dataset_id"] == "acme/db"


def test_match_route_package_favorite() -> None:
    posted = match_route("POST", "/v1/packages/acme/echo/favorite")
    assert posted is not None
    assert posted[0].name == "put_package_favorite"
    assert posted[1]["dataset_id"] == "acme/echo"
    deleted = match_route("DELETE", "/v1/packages/acme/echo/favorite")
    assert deleted is not None
    assert deleted[0].name == "delete_package_favorite"
    listed = match_route("GET", "/v1/packages/acme/echo")
    assert listed is not None
    assert listed[0].name == "list_package_versions"


def test_match_route_package_version_meta() -> None:
    matched = match_route("GET", "/v1/packages/acme/db/versions/1.0.0")
    assert matched is not None
    route, kwargs = matched
    assert route.name == "serve_meta"
    assert kwargs["dataset_id"] == "acme/db"
    assert kwargs["version"] == "1.0.0"
    assert kwargs["package_digest"] is None


def test_upsert_token_does_not_bind_created_at() -> None:
    # Live Postgres api_tokens.created_at is timestamptz; epoch floats fail.
    assert "created_at" not in Q.UPSERT_TOKEN


def test_sqlite_align_integer_flag_is_noop(tmp_path) -> None:
    from services.registry.sql_adapter import SqliteAdapter

    adapter = SqliteAdapter(tmp_path / "meta.sqlite3")
    with adapter.connect() as conn:
        adapter.align_integer_flag(conn, "organizations", "is_claimable")


def test_sqlite_lock_schema_is_noop(tmp_path) -> None:
    from services.registry.sql_adapter import SqliteAdapter

    adapter = SqliteAdapter(tmp_path / "meta.sqlite3")
    with adapter.connect() as conn:
        adapter.lock_schema(conn)


def test_postgres_lock_schema_uses_xact_advisory_lock() -> None:
    from services.registry.sql_adapter import (
        _SCHEMA_LOCK_ID,
        _SCHEMA_LOCK_NS,
        PostgresAdapter,
    )

    recorded: list[tuple[str, object]] = []
    fake = object.__new__(PostgresAdapter)

    def _execute(_conn: object, sql: str, params: object = ()) -> None:
        recorded.append((sql, params))

    fake.execute = _execute  # type: ignore[method-assign]
    fake.lock_schema(object())
    assert recorded == [
        ("SELECT pg_advisory_xact_lock(?, ?)", (_SCHEMA_LOCK_NS, _SCHEMA_LOCK_ID)),
    ]


def test_postgres_add_column_skips_when_present() -> None:
    from services.registry.sql_adapter import PostgresAdapter

    executed: list[str] = []

    class _Conn:
        def execute(self, sql: str, params: object = ()) -> None:
            executed.append(sql)

    fake = object.__new__(PostgresAdapter)
    fake.table_columns = lambda _conn, _table: {"org_id"}  # type: ignore[method-assign]
    PostgresAdapter.add_column(fake, _Conn(), "releases", "org_id", "TEXT")
    assert executed == []


def test_metadata_and_token_init_take_schema_lock(tmp_path, monkeypatch) -> None:
    from services.registry.sql_adapter import SqliteAdapter
    from services.registry.store import SqliteTokenStore
    from services.registry.store_schema import open_sqlite_stores

    calls: list[str] = []
    orig = SqliteAdapter.lock_schema

    def _spy(self: SqliteAdapter, conn: object) -> None:
        calls.append(self.name)
        orig(self, conn)

    monkeypatch.setattr(SqliteAdapter, "lock_schema", _spy)
    db = tmp_path / "meta.sqlite3"
    open_sqlite_stores(db)
    SqliteTokenStore(db)
    assert calls == ["sqlite", "sqlite"]


def test_align_integer_flag_rejects_bad_ident() -> None:
    import pytest
    from services.registry.sql_adapter import PostgresAdapter

    fake = object.__new__(PostgresAdapter)
    with pytest.raises(ValueError, match="identifier"):
        fake.align_integer_flag(None, "organizations;drop", "is_claimable")


def test_store_has_no_sql_literals() -> None:
    from pathlib import Path

    needles = ("DELETE FROM", "INSERT INTO", "CREATE TABLE", "UPDATE ")
    registry = Path(__file__).resolve().parents[2] / "services" / "registry"
    offenders: list[str] = []
    for path in sorted(registry.glob("store*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(n in line for n in needles):
                offenders.append(f"{path.name}:{i}:{stripped}")
    assert offenders == []


def test_match_route_health_skip_auth() -> None:
    matched = match_route("GET", "/health")
    assert matched is not None
    route, _kwargs = matched
    assert route.name == "health"
    assert route.skip_auth is True
