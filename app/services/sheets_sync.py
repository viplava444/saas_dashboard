"""
app/services/sheets_sync.py
────────────────────────────
Enterprise-grade bidirectional sync between Google Sheets and local SQLite.

HOW IT WORKS
────────────
                    ┌─────────────────────────────┐
                    │       Google Sheets          │
                    │  users | app_access | audit  │
                    │  sessions | app_registry     │
                    └──────────┬──────────┬────────┘
                   pull on     │          │  push on
                   cold start  │          │  every write
                    ┌──────────▼──────────▼────────┐
                    │      Local SQLite (fast)      │
                    │   ephemeral — resets on       │
                    │   every Streamlit redeploy    │
                    └───────────────────────────────┘

COLD-START RESTORE (called once per server process in main.py)
──────────────────────────────────────────────────────────────
1. Pull all rows from Sheets for every table.
2. Upsert into local SQLite via existing DAOs.
3. App is ready in seconds.

WRITE MIRROR (called after every mutating DB operation)
───────────────────────────────────────────────────────
Every service method that writes to SQLite also calls the corresponding
push_* helper here.  Failures are logged but never raise — a network
blip must not break user-facing operations.

FAILURE STRATEGY
────────────────
Best-effort: Sheets calls are wrapped in try/except.  If the API is
unreachable, a WARNING is logged and the SQLite operation is unaffected.
The next successful write brings Sheets back in sync.

MODULE-LEVEL SINGLETON
──────────────────────
Call SheetsSync.init() once in main.py.  All other modules import this
module and call the push_* / restore_* helpers directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.sheets_client import SheetsClient, SheetsAPIError

logger = logging.getLogger(__name__)

# ── Singleton client ──────────────────────────────────────────────────────────
_client: SheetsClient | None = None


def init(endpoint_url: str, secret: str) -> None:
    """Initialise the Sheets sync layer. Call once at app startup."""
    global _client
    _client = SheetsClient(endpoint_url=endpoint_url, secret=secret)
    logger.info("SheetsSync initialised (endpoint configured).")


def is_enabled() -> bool:
    return _client is not None


# ═════════════════════════════════════════════════════════════════════════════
# COLD-START RESTORE
# ═════════════════════════════════════════════════════════════════════════════

def restore_all(db_conn) -> dict[str, int]:
    """
    Pull every table from Google Sheets and upsert into local SQLite.

    Parameters
    ----------
    db_conn : sqlite3.Connection
        An open connection to the local nexusops.db / viplavaforge.db.

    Returns
    -------
    dict mapping table_name → number of rows restored.
    """
    if not is_enabled():
        logger.warning("SheetsSync not initialised — restore skipped.")
        return {}

    counts: dict[str, int] = {}

    counts["users"]           = _restore_users(db_conn)
    counts["user_app_access"] = _restore_app_access(db_conn)
    counts["sessions"]        = _restore_sessions(db_conn)
    counts["app_registry"]    = _restore_app_registry(db_conn)
    # audit_log is append-only; we do NOT restore it into SQLite on startup
    # (it can grow very large). The admin UI reads it directly from Sheets.

    logger.info("Cold-start restore complete: %s", counts)
    return counts


# ─── Individual restore helpers ───────────────────────────────────────────────

def _restore_users(conn) -> int:
    try:
        rows = _client.get_all_users()
    except SheetsAPIError as exc:
        logger.error("restore_users failed: %s", exc)
        return 0

    count = 0
    for r in rows:
        email = str(r.get("email", "")).strip().lower()
        if not email:
            continue
        try:
            existing = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE users SET
                        full_name     = ?,
                        password_hash = ?,
                        role          = ?,
                        status        = ?,
                        failed_logins = ?,
                        locked_until  = ?,
                        last_login    = ?,
                        last_ip       = ?,
                        updated_at    = ?
                    WHERE email = ?""",
                    (
                        r.get("full_name", ""),
                        r.get("password_hash", ""),
                        r.get("role", "user"),
                        r.get("status", "pending"),
                        int(r.get("failed_logins") or 0),
                        r.get("locked_until") or None,
                        r.get("last_login")   or None,
                        r.get("last_ip")      or None,
                        r.get("updated_at")   or _now(),
                        email,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO users
                        (email, full_name, password_hash, role, status,
                         failed_logins, locked_until, last_login, last_ip,
                         created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        email,
                        r.get("full_name", ""),
                        r.get("password_hash", ""),
                        r.get("role", "user"),
                        r.get("status", "pending"),
                        int(r.get("failed_logins") or 0),
                        r.get("locked_until") or None,
                        r.get("last_login")   or None,
                        r.get("last_ip")      or None,
                        r.get("created_at")   or _now(),
                        r.get("updated_at")   or _now(),
                    ),
                )
            count += 1
        except Exception as exc:
            logger.warning("Failed to restore user '%s': %s", email, exc)

    conn.commit()
    return count


def _restore_app_access(conn) -> int:
    try:
        rows = _client.get_all_app_access()
    except SheetsAPIError as exc:
        logger.error("restore_app_access failed: %s", exc)
        return 0

    count = 0
    for r in rows:
        try:
            user_id = int(r.get("user_id") or 0)
            app_id  = str(r.get("app_id", "")).strip()
            if not user_id or not app_id:
                continue

            revoked_at = r.get("revoked_at") or None

            existing = conn.execute(
                "SELECT id FROM user_app_access WHERE user_id=? AND app_id=?",
                (user_id, app_id),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE user_app_access SET revoked_at=? WHERE user_id=? AND app_id=?",
                    (revoked_at, user_id, app_id),
                )
            else:
                conn.execute(
                    """INSERT INTO user_app_access
                       (user_id, app_id, granted_at, granted_by, revoked_at)
                       VALUES (?,?,?,?,?)""",
                    (
                        user_id,
                        app_id,
                        r.get("granted_at") or _now(),
                        r.get("granted_by") or 0,
                        revoked_at,
                    ),
                )
            count += 1
        except Exception as exc:
            logger.warning("Failed to restore app_access row: %s — %s", r, exc)

    conn.commit()
    return count


def _restore_sessions(conn) -> int:
    """Restore non-revoked, non-expired sessions."""
    try:
        rows = _client._get(action="get_sheet", sheet="sessions").get("rows", [])
    except SheetsAPIError as exc:
        logger.error("restore_sessions failed: %s", exc)
        return 0

    now   = _now()
    count = 0
    for r in rows:
        try:
            token   = str(r.get("session_token", "")).strip()
            revoked = str(r.get("revoked", "")).lower() in ("true", "1", "yes")
            expires = str(r.get("expires_at", ""))

            if not token or revoked or (expires and expires < now):
                continue

            existing = conn.execute(
                "SELECT id FROM sessions WHERE session_token=?", (token,)
            ).fetchone()

            if not existing:
                conn.execute(
                    """INSERT INTO sessions
                       (user_id, session_token, created_at, expires_at, revoked)
                       VALUES (?,?,?,?,?)""",
                    (
                        int(r.get("user_id") or 0),
                        token,
                        r.get("created_at") or _now(),
                        expires or None,
                        0,
                    ),
                )
                count += 1
        except Exception as exc:
            logger.warning("Failed to restore session: %s", exc)

    conn.commit()
    return count


def _restore_app_registry(conn) -> int:
    """
    Sync app registry from Sheets into the local config-driven list.
    Only writes to the ``remote_apps`` table if it exists; silently skips
    otherwise (the config/settings.py AVAILABLE_APPS list still works).
    """
    try:
        rows = _client.get_app_registry()
    except SheetsAPIError as exc:
        logger.error("restore_app_registry failed: %s", exc)
        return 0

    # Only restore if the project has a remote_apps table
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='remote_apps'"
    ).fetchone()

    if not has_table:
        return 0

    count = 0
    for r in rows:
        app_id = str(r.get("app_id", "")).strip()
        if not app_id:
            continue
        try:
            existing = conn.execute(
                "SELECT id FROM remote_apps WHERE app_id=?", (app_id,)
            ).fetchone()
            enabled = str(r.get("enabled", "true")).lower() not in ("false", "0", "no")
            if existing:
                conn.execute(
                    """UPDATE remote_apps SET
                       name=?, description=?, icon=?,
                       module_path=?, category=?, enabled=?
                    WHERE app_id=?""",
                    (r.get("name",""), r.get("description",""), r.get("icon",""),
                     r.get("module_path",""), r.get("category",""), enabled, app_id),
                )
            else:
                conn.execute(
                    """INSERT INTO remote_apps
                       (app_id,name,description,icon,module_path,category,enabled,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (app_id, r.get("name",""), r.get("description",""),
                     r.get("icon",""), r.get("module_path",""),
                     r.get("category",""), enabled, r.get("created_at", _now())),
                )
            count += 1
        except Exception as exc:
            logger.warning("Failed to restore app '%s': %s", app_id, exc)

    conn.commit()
    return count


# ═════════════════════════════════════════════════════════════════════════════
# PUSH HELPERS  (call after every SQLite write)
# ═════════════════════════════════════════════════════════════════════════════

def push_user(user_dict: dict[str, Any]) -> None:
    """
    Mirror one user to Google Sheets.

    Accepts a plain dict (easier than importing User dataclass here).
    Keys mirror the ``users`` sheet columns.
    """
    if not is_enabled():
        return
    try:
        _client.upsert_user(**user_dict)
        logger.debug("Pushed user '%s' to Sheets.", user_dict.get("email"))
    except SheetsAPIError as exc:
        logger.warning("push_user failed for '%s': %s", user_dict.get("email"), exc)


def push_app_access(
    user_id: int,
    app_id: str,
    granted_by: int,
    revoked_at: str | None = None,
) -> None:
    """Mirror a grant or revoke to the user_app_access sheet."""
    if not is_enabled():
        return
    try:
        _client.upsert_app_access(
            user_id    = user_id,
            app_id     = app_id,
            granted_at = _now(),
            granted_by = granted_by,
            revoked_at = revoked_at or "",
        )
    except SheetsAPIError as exc:
        logger.warning("push_app_access failed: %s", exc)


def push_audit(
    actor_id: int | str,
    actor_email: str,
    action: str,
    target: str = "",
    detail: str = "",
    ip_address: str = "",
    session_id: str = "",
) -> None:
    """Append one row to the audit_log sheet."""
    if not is_enabled():
        return
    try:
        _client.append_audit(
            actor_id     = actor_id,
            actor_email  = actor_email,
            audit_action = action,
            target       = target,
            detail       = detail,
            ip_address   = ip_address,
            session_id   = session_id,
            created_at   = _now(),
        )
    except SheetsAPIError as exc:
        logger.warning("push_audit failed: %s", exc)


def push_session(
    user_id: int,
    session_token: str,
    expires_at: str,
) -> None:
    """Write a new session to the sessions sheet."""
    if not is_enabled():
        return
    try:
        _client.upsert_session(
            user_id       = user_id,
            session_token = session_token,
            created_at    = _now(),
            expires_at    = expires_at,
            revoked       = False,
        )
    except SheetsAPIError as exc:
        logger.warning("push_session failed: %s", exc)


def revoke_session(session_token: str) -> None:
    """Mark a session as revoked in the sessions sheet."""
    if not is_enabled():
        return
    try:
        _client.revoke_session(session_token)
    except SheetsAPIError as exc:
        logger.warning("revoke_session failed: %s", exc)


def push_app_registry(app_dict: dict) -> None:
    """Upsert one app definition into the app_registry sheet."""
    if not is_enabled():
        return
    try:
        _client.upsert_app_registry(**app_dict)
    except SheetsAPIError as exc:
        logger.warning("push_app_registry failed: %s", exc)


# ─── Utility ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
