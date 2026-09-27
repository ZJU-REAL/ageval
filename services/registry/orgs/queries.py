"""Org, membership, invite, and user-profile SQL."""

from __future__ import annotations

from typing import Any

INSERT_ORG = """
INSERT INTO organizations(
    org_id, name, display_name, description, is_claimable, created_at
) VALUES (?, ?, ?, ?, ?, ?)
"""

INSERT_ORG_OWNER_MEMBERSHIP = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, 'owner', ?)
"""

SELECT_ORG = "SELECT * FROM organizations WHERE org_id=?"

def update_org_query(*, display_name: bool, description: bool, icons: bool) -> str:
    sets: list[str] = []
    if display_name:
        sets.append("display_name=?")
    if description:
        sets.append("description=?")
    if icons:
        sets.append("icon_key=?")
        sets.append("icon_github=?")
    return f"UPDATE organizations SET {', '.join(sets)} WHERE org_id=?"

SELECT_MEMBERSHIP = "SELECT * FROM org_memberships WHERE org_id=? AND user_id=?"

SELECT_USER_ORG_IDS = "SELECT org_id FROM org_memberships WHERE user_id=?"

SELECT_USER_ORGS = """
SELECT o.*, m.role AS membership_role
FROM organizations o
JOIN org_memberships m ON m.org_id = o.org_id
WHERE m.user_id = ?
ORDER BY o.name
"""

SELECT_ORG_HAS_OWNER = "SELECT 1 FROM org_memberships WHERE org_id=? AND role='owner' LIMIT 1"

INSERT_ORG_MEMBERSHIP_OWNER = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, 'owner', ?)
"""

UPDATE_ORG_CLAIMED = "UPDATE organizations SET is_claimable=0 WHERE org_id=?"

INSERT_ORG_MEMBERSHIP = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, ?, ?)
"""

DELETE_ORG_MEMBERSHIP = "DELETE FROM org_memberships WHERE org_id=? AND user_id=?"

UPDATE_ORG_MEMBERSHIP_ROLE = "UPDATE org_memberships SET role=? WHERE org_id=? AND user_id=?"

COUNT_ORG_OWNERS = "SELECT COUNT(*) AS n FROM org_memberships WHERE org_id=? AND role='owner'"

COUNT_ORG_PACKAGES = "SELECT COUNT(*) AS n FROM releases WHERE org_id=?"

DELETE_ORG_INVITE_KEYS = "DELETE FROM org_invite_keys WHERE org_id=?"

DELETE_ORG_MEMBERSHIPS = "DELETE FROM org_memberships WHERE org_id=?"

DELETE_ORG_RESULT_SHARES = "DELETE FROM result_shares WHERE target_type='org' AND target_id=?"

DELETE_ORG = "DELETE FROM organizations WHERE org_id=?"

SELECT_ORG_MEMBERS = """
SELECT org_id, user_id, role, created_at
FROM org_memberships
WHERE org_id=?
ORDER BY CASE WHEN role = 'owner' THEN 0 ELSE 1 END, user_id
"""

INSERT_INVITE_KEY = """
INSERT INTO org_invite_keys(
    key_id, org_id, token_hash, token_prefix, created_by,
    max_uses, use_count, expires_at, revoked_at, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_INVITE_KEYS = """
SELECT * FROM org_invite_keys
WHERE org_id=?
ORDER BY created_at DESC
"""

SELECT_INVITE_KEY = "SELECT * FROM org_invite_keys WHERE org_id=? AND key_id=?"

UPDATE_INVITE_REVOKED = "UPDATE org_invite_keys SET revoked_at=? WHERE key_id=?"

SELECT_INVITE_BY_HASH = "SELECT * FROM org_invite_keys WHERE token_hash=?"

CLAIM_INVITE_USE = """
UPDATE org_invite_keys
SET use_count = use_count + 1
WHERE key_id=? AND (max_uses IS NULL OR use_count < max_uses)
"""

INSERT_ORG_MEMBERSHIP_MEMBER = """
INSERT INTO org_memberships(org_id, user_id, role, created_at)
VALUES (?, ?, 'member', ?)
"""

UPSERT_USER_PROFILE = """
INSERT INTO user_profiles(
    user_id, display_name, avatar_url, github_id, description, updated_at
) VALUES (?, ?, ?, ?, '', ?)
ON CONFLICT(user_id) DO UPDATE SET
    display_name=excluded.display_name,
    avatar_url=excluded.avatar_url,
    github_id=excluded.github_id,
    updated_at=excluded.updated_at
"""

SELECT_USER_PROFILE = "SELECT * FROM user_profiles WHERE user_id=?"

UPSERT_USER_DESCRIPTION = """
INSERT INTO user_profiles(
    user_id, display_name, avatar_url, github_id, description, updated_at
) VALUES (?, '', '', '', ?, ?)
ON CONFLICT(user_id) DO UPDATE SET
    description=excluded.description,
    updated_at=excluded.updated_at
"""

def select_user_profiles_in_query(n: int) -> str:
    placeholders = ",".join("?" for _ in range(n))
    return f"SELECT * FROM user_profiles WHERE user_id IN ({placeholders})"

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS organizations (
        org_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        icon_key TEXT NOT NULL DEFAULT '',
        icon_github TEXT NOT NULL DEFAULT '',
        is_claimable INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS org_memberships (
        org_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (org_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL DEFAULT '',
        avatar_url TEXT NOT NULL DEFAULT '',
        github_id TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS org_invite_keys (
        key_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        token_prefix TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        max_uses INTEGER,
        use_count INTEGER NOT NULL DEFAULT 0,
        expires_at REAL,
        revoked_at REAL,
        created_at REAL NOT NULL
    )
    """,
)

SCHEMA_INTEGER_FLAGS: tuple[tuple[str, str], ...] = (
    ("organizations", "is_claimable"),
)

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("organizations", "description", "TEXT NOT NULL DEFAULT ''"),
    ("user_profiles", "description", "TEXT NOT NULL DEFAULT ''"),
    ("organizations", "icon_key", "TEXT NOT NULL DEFAULT ''"),
    ("organizations", "icon_github", "TEXT NOT NULL DEFAULT ''"),
)
