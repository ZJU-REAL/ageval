"""API token stores: in-memory (tests) and persistent SQLite / Postgres.

Raw tokens are never stored — only sha256 digests. ``api_tokens`` DDL and
writes live here; aggregate schema init does not create that table.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from services.registry.orgs.rows import normalize_user_id

# Do not bind created_at. Pre-unification Postgres token tables are
# TIMESTAMPTZ DEFAULT now(); an epoch float fails to insert. New tables
# use REAL DEFAULT 0. Token created_at is never read.
API_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    scopes TEXT NOT NULL,
    github_user TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    revoked_at REAL
)
"""

UPSERT_TOKEN = """
INSERT INTO api_tokens(token_hash, scopes, github_user)
VALUES (?, ?, ?)
ON CONFLICT(token_hash) DO UPDATE SET
    scopes=excluded.scopes,
    github_user=excluded.github_user,
    revoked_at=NULL
"""

SELECT_TOKEN = "SELECT scopes, github_user, revoked_at FROM api_tokens WHERE token_hash=?"


@dataclass(frozen=True, slots=True)
class TokenInfo:
    """Resolved bearer token: scopes + optional user identity (github login)."""

    scopes: frozenset[str]
    user_id: str | None = None


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


DEFAULT_LOGIN_SCOPES: frozenset[str] = frozenset(
    {
        "registry:publish",
        "read-private",
        "results:upload",
        "results:read",
    }
)

ADMIN_SCOPES: frozenset[str] = frozenset(
    {
        "admin",
        "registry:publish",
        "read-private",
        "results:upload",
        "results:read",
    }
)



@runtime_checkable
class TokenStoreProtocol(Protocol):
    def hash_token(self, raw: str) -> str: ...

    def add(
        self,
        raw_token: str,
        scopes: frozenset[str] | set[str],
        *,
        github_user: str | None = None,
    ) -> None: ...

    def auth_for(self, raw_token: str | None) -> TokenInfo: ...

    def scopes_for(self, raw_token: str | None) -> frozenset[str]: ...


class TokenStore(TokenStoreProtocol):
    """In-memory tokens (tests). Prefer SqliteTokenStore / PostgresTokenStore."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, TokenInfo] = {}

    def hash_token(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def add(
        self,
        raw_token: str,
        scopes: set[str] | frozenset[str],
        *,
        github_user: str | None = None,
    ) -> None:
        with self._lock:
            self._tokens[self.hash_token(raw_token)] = TokenInfo(
                scopes=frozenset(scopes),
                user_id=normalize_user_id(github_user),
            )

    def auth_for(self, raw_token: str | None) -> TokenInfo:
        if not raw_token:
            return TokenInfo(scopes=frozenset())
        with self._lock:
            return self._tokens.get(self.hash_token(raw_token), TokenInfo(scopes=frozenset()))

    def scopes_for(self, raw_token: str | None) -> frozenset[str]:
        return self.auth_for(raw_token).scopes


class PersistentTokenStore(TokenStoreProtocol):
    """One token repository; SQLite / Postgres only differ in the adapter."""

    def __init__(self, *, adapter: Any) -> None:
        self._adapter = adapter
        self.db_path = getattr(adapter, "db_path", None)
        self._init()

    def _connect(self) -> Any:
        return self._adapter.connect()

    def _exec(self, conn: Any, sql: str, params: Any = ()) -> Any:
        return self._adapter.execute(conn, sql, params)

    def _init(self) -> None:
        with self._connect() as conn:
            self._adapter.lock_schema(conn)
            self._exec(conn, API_TOKENS_DDL)
            conn.commit()

    def hash_token(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def add(
        self,
        raw_token: str,
        scopes: set[str] | frozenset[str],
        *,
        github_user: str | None = None,
    ) -> None:
        scopes_json = json.dumps(sorted(scopes))
        with self._connect() as conn:
            self._exec(
                conn,
                UPSERT_TOKEN,
                (self.hash_token(raw_token), scopes_json, github_user),
            )
            conn.commit()

    def auth_for(self, raw_token: str | None) -> TokenInfo:
        if not raw_token:
            return TokenInfo(scopes=frozenset())
        with self._connect() as conn:
            cur = self._exec(conn, SELECT_TOKEN, (self.hash_token(raw_token),))
            row = cur.fetchone()
            if row is None or row.get("revoked_at") is not None:
                return TokenInfo(scopes=frozenset())
            scopes_raw = row["scopes"]
            try:
                data = scopes_raw if isinstance(scopes_raw, list) else json.loads(scopes_raw)
            except (TypeError, json.JSONDecodeError):
                return TokenInfo(scopes=frozenset())
            return TokenInfo(
                scopes=frozenset(str(s) for s in data),
                user_id=normalize_user_id(row["github_user"]),
            )

    def scopes_for(self, raw_token: str | None) -> frozenset[str]:
        return self.auth_for(raw_token).scopes


class SqliteTokenStore(PersistentTokenStore):
    """Persistent tokens in the same SQLite file as metadata."""

    def __init__(self, db_path: Path) -> None:
        from services.registry.db.sql_adapter import SqliteAdapter

        PersistentTokenStore.__init__(self, adapter=SqliteAdapter(db_path))


class PostgresTokenStore(PersistentTokenStore):
    """Persistent tokens in Postgres."""

    def __init__(self, database_url: str) -> None:
        from services.registry.db.sql_adapter import PostgresAdapter

        PersistentTokenStore.__init__(self, adapter=PostgresAdapter(database_url))
        self.database_url = database_url
