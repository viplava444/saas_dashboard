"""
app/models/database_migration.py
──────────────────────────────────
Safe, additive migration for the existing nexusops.db schema.

Adds the columns and tables needed for enterprise-grade persistence
without touching anything that already exists.  Run once at startup
in main.py — it is fully idempotent (safe to run on every boot).

NEW COLUMNS added to `users`
─────────────────────────────
  failed_logins  INTEGER DEFAULT 0
  locked_until   TEXT             ← ISO-8601 UTC timestamp or NULL
  last_login     TEXT             ← ISO-8601 UTC timestamp or NULL
  last_ip        TEXT             ← last known IP address or NULL
  updated_at     TEXT             ← ISO-8601 UTC timestamp

NEW COLUMNS added to `user_app_access`
───────────────────────────────────────
  revoked_at     TEXT             ← NULL means currently active

NEW TABLE: sessions
────────────────────
  Tracks active login sessions so they survive redeploys.

NEW TABLE: remote_apps  (optional, only if you want Sheets-driven app registry)
────────────────────────
  Mirrors app_registry sheet.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply all pending migrations.  Safe to call on every startup.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to the project database.
    """
    _add_user_columns(conn)
    _add_app_access_columns(conn)
    _create_sessions_table(conn)
    _create_remote_apps_table(conn)
    conn.commit()
    logger.info("Database migrations applied.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        logger.debug("Added column %s.%s", table, column)


# ─── Migrations ───────────────────────────────────────────────────────────────

def _add_user_columns(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "users"):
        return
    _add_column_if_missing(conn, "users", "failed_logins", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "users", "locked_until",  "TEXT")
    _add_column_if_missing(conn, "users", "last_login",    "TEXT")
    _add_column_if_missing(conn, "users", "last_ip",       "TEXT")
    _add_column_if_missing(conn, "users", "updated_at",    "TEXT")


def _add_app_access_columns(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "user_app_access"):
        return
    _add_column_if_missing(conn, "user_app_access", "revoked_at", "TEXT")


def _create_sessions_table(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "sessions"):
        return
    conn.execute(
        """
        CREATE TABLE sessions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_token TEXT    NOT NULL UNIQUE,
            created_at    TEXT    NOT NULL,
            expires_at    TEXT,
            revoked       INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX idx_sessions_token   ON sessions(session_token)")
    conn.execute("CREATE INDEX idx_sessions_user_id ON sessions(user_id)")
    logger.debug("Created table: sessions")


def _create_remote_apps_table(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "remote_apps"):
        return
    conn.execute(
        """
        CREATE TABLE remote_apps (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id      TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            description TEXT,
            icon        TEXT,
            module_path TEXT NOT NULL,
            category    TEXT,
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_remote_apps_app_id ON remote_apps(app_id)")
    logger.debug("Created table: remote_apps")
