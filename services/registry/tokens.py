"""API token stores: in-memory (tests) and persistent SQLite / Postgres.

Raw tokens are never stored — only sha256 digests. Schema bootstrap for
``api_tokens`` lives here (``PersistentTokenStore._init``), the one statement
group the metadata schema init skips.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.registry import queries as Q
from services.registry.protocols import TokenStoreProtocol


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


def _normalize_user_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    u = str(raw).strip()
    if not u:
        return None
    return u.casefold()


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
                user_id=_normalize_user_id(github_user),
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
            for stmt in Q.SCHEMA_STATEMENTS:
                if "api_tokens" in stmt:
                    self._exec(conn, stmt)
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
                Q.UPSERT_TOKEN,
                (self.hash_token(raw_token), scopes_json, github_user),
            )
            conn.commit()

    def auth_for(self, raw_token: str | None) -> TokenInfo:
        if not raw_token:
            return TokenInfo(scopes=frozenset())
        with self._connect() as conn:
            cur = self._exec(conn, Q.SELECT_TOKEN, (self.hash_token(raw_token),))
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
                user_id=_normalize_user_id(row["github_user"]),
            )

    def scopes_for(self, raw_token: str | None) -> frozenset[str]:
        return self.auth_for(raw_token).scopes


class SqliteTokenStore(PersistentTokenStore):
    """Persistent tokens in the same SQLite file as metadata."""

    def __init__(self, db_path: Path) -> None:
        from services.registry.sql_adapter import SqliteAdapter

        PersistentTokenStore.__init__(self, adapter=SqliteAdapter(db_path))


class PostgresTokenStore(PersistentTokenStore):
    """Persistent tokens in Postgres."""

    def __init__(self, database_url: str) -> None:
        from services.registry.sql_adapter import PostgresAdapter

        PersistentTokenStore.__init__(self, adapter=PostgresAdapter(database_url))
        self.database_url = database_url
