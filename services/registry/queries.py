"""Shared SQL text for Registry metadata stores (SQLite ``?`` placeholders).

Postgres adapters rewrite placeholders in :mod:`services.registry.db.sql_adapter`.
DDL lives here once; dialect adapters only connect / placeholder / row-map.
"""

from __future__ import annotations

from typing import Any

# ---- releases --------------------------------------------------------------




# ---- attempt / suite results -----------------------------------------------

# ---- orgs ------------------------------------------------------------------



# Types chosen so SQLite and Postgres accept the same CREATE TABLE text.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
        token_hash TEXT PRIMARY KEY,
        scopes TEXT NOT NULL,
        github_user TEXT,
        created_at REAL NOT NULL DEFAULT 0,
        revoked_at REAL
    )
    """,
)

# ---- dataset draft / ACL ---------------------------------------------------

DELETE_DATASET_ACL = "DELETE FROM dataset_acl WHERE dataset_id=? AND user_id=?"

# Live Postgres may have created these as BOOLEAN; inserts bind 0/1 (INTEGER).
SCHEMA_INTEGER_FLAGS: tuple[tuple[str, str], ...] = (
)

# (table, column, sqlite/postgres-compatible type clause)
SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    # API names are error and limit. `limit` is reserved in Postgres.
)

# Do not bind created_at. Pre-unification Postgres token tables are
# TIMESTAMPTZ DEFAULT now(); an epoch float fails to insert. New tables
# use REAL DEFAULT 0. Token created_at is never read.
UPSERT_TOKEN = """
INSERT INTO api_tokens(token_hash, scopes, github_user)
VALUES (?, ?, ?)
ON CONFLICT(token_hash) DO UPDATE SET
    scopes=excluded.scopes,
    github_user=excluded.github_user,
    revoked_at=NULL
"""

SELECT_TOKEN = "SELECT scopes, github_user, revoked_at FROM api_tokens WHERE token_hash=?"

# ---- remaining store SQL ---------------------------------------------------

