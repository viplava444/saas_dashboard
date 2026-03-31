"""
app/models/user.py  —  User data-access object (DAO)
"""

from dataclasses import dataclass
from typing import Optional, List
from app.models.database import get_db


@dataclass
class User:
    id: int
    email: str
    full_name: str
    password_hash: str
    role: str
    status: str
    failed_logins: int
    locked_until: Optional[str]
    created_at: str
    updated_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def display_name(self) -> str:
        return self.full_name or self.email


class UserDAO:

    # ── Retrieval ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_by_email(email: str) -> Optional[User]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
            return User(**dict(row)) if row else None

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return User(**dict(row)) if row else None

    @staticmethod
    def get_all(role: Optional[str] = None) -> List[User]:
        with get_db() as conn:
            if role:
                rows = conn.execute(
                    "SELECT * FROM users WHERE role = ? ORDER BY created_at DESC", (role,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM users ORDER BY created_at DESC"
                ).fetchall()
            return [User(**dict(r)) for r in rows]

    @staticmethod
    def get_pending() -> List[User]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE status = 'pending' AND role != 'admin' ORDER BY created_at"
            ).fetchall()
            return [User(**dict(r)) for r in rows]

    # ── Creation ───────────────────────────────────────────────────────────────

    @staticmethod
    def create(email: str, full_name: str, password_hash: str,
               role: str = "user", status: str = "pending") -> int:
        with get_db() as conn:
            cur = conn.execute(
                """INSERT INTO users (email, full_name, password_hash, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (email.lower().strip(), full_name.strip(), password_hash, role, status)
            )
            return cur.lastrowid

    # ── Updates ────────────────────────────────────────────────────────────────

    @staticmethod
    def update_status(user_id: int, status: str):
        with get_db() as conn:
            conn.execute(
                "UPDATE users SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, user_id)
            )

    @staticmethod
    def increment_failed_login(user_id: int):
        with get_db() as conn:
            conn.execute(
                "UPDATE users SET failed_logins = failed_logins + 1, updated_at = datetime('now') WHERE id = ?",
                (user_id,)
            )

    @staticmethod
    def reset_failed_logins(user_id: int):
        with get_db() as conn:
            conn.execute(
                "UPDATE users SET failed_logins = 0, locked_until = NULL, updated_at = datetime('now') WHERE id = ?",
                (user_id,)
            )

    @staticmethod
    def set_lockout(user_id: int, until: str):
        with get_db() as conn:
            conn.execute(
                "UPDATE users SET locked_until = ?, updated_at = datetime('now') WHERE id = ?",
                (until, user_id)
            )

    # ── App Access ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_app_access(user_id: int) -> List[str]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT app_id FROM user_app_access WHERE user_id = ?", (user_id,)
            ).fetchall()
            return [r["app_id"] for r in rows]

    @staticmethod
    def grant_app(user_id: int, app_id: str, granted_by: int):
        with get_db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO user_app_access (user_id, app_id, granted_by)
                   VALUES (?, ?, ?)""",
                (user_id, app_id, granted_by)
            )

    @staticmethod
    def revoke_app(user_id: int, app_id: str):
        with get_db() as conn:
            conn.execute(
                "DELETE FROM user_app_access WHERE user_id = ? AND app_id = ?",
                (user_id, app_id)
            )
