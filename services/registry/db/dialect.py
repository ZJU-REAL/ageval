"""SQL dialect helpers shared by SQLite / Postgres metadata adapters.

Query text should be authored once with ``?`` placeholders; Postgres adapters
call ``pg_sql`` before execute. Connection / row mapping stay in each store.
"""

from __future__ import annotations


def pg_sql(sql: str) -> str:
    """Translate SQLite-style ``?`` placeholders to psycopg ``%s``."""
    return sql.replace("?", "%s")
