"""
app/services/auth_service.py  —  Authentication business logic
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

from app.models.audit import AuditDAO
from app.models.database import get_db, init_db
from app.models.user import User, UserDAO
from app.services import sheets_sync
from config.settings import (
    ADMIN_EMAIL,
    ADMIN_NAME,
    ADMIN_PASSWORD,
    LOCKOUT_MINUTES,
    MAX_LOGIN_ATTEMPTS,
    PASSWORD_MIN_LENGTH,
    ROLE_ADMIN,
    ROLE_USER,
    STATUS_APPROVED,
    STATUS_PENDING,
)


class AuthService:

    def __init__(self):
        init_db()
        self._bootstrap_admin()

    # ── Public API ─────────────────────────────────────────────────────────────

    @staticmethod
    def register(email: str, full_name: str, password: str) -> Tuple[bool, str]:
        """
        Register a new user.

        Validates inputs, checks for duplicate email, hashes the password
        with PBKDF2-SHA256, inserts into local SQLite, then mirrors the
        new user to Google Sheets (best-effort).

        Returns (success: bool, message: str).
        """
        email     = email.strip().lower()
        full_name = full_name.strip()

        # ── Validation ────────────────────────────────────────────────
        valid, msg = AuthService._validate_registration(email, full_name, password)
        if not valid:
            return False, msg

        if UserDAO.get_by_email(email):
            return False, "An account with this email already exists."

        # ── Hash + insert ─────────────────────────────────────────────
        password_hash = AuthService._hash_password(password)
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        with get_db() as conn:
            cur = conn.execute(
                """INSERT INTO users
                   (email, full_name, password_hash, role, status,
                    failed_logins, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (email, full_name, password_hash, ROLE_USER,
                 STATUS_PENDING, 0, now, now),
            )
            user_id = cur.lastrowid
            conn.commit()

        # ── Mirror to Sheets (best-effort) ────────────────────────────
        sheets_sync.push_user({
            "email":         email,
            "full_name":     full_name,
            "password_hash": password_hash,
            "role":          ROLE_USER,
            "status":        STATUS_PENDING,
            "failed_logins": 0,
            "created_at":    now,
            "updated_at":    now,
        })
        sheets_sync.push_audit(
            actor_id    = user_id,
            actor_email = email,
            action      = "user_registered",
            target      = email,
        )

        return True, "Registration successful. Awaiting admin approval."

    @staticmethod
    def login(email: str, password: str, ip: str = "") -> Tuple[bool, str]:
        """
        Validate credentials and return (success: bool, message: str).

        Tracks failed_logins, locked_until, last_login, and last_ip in
        both local SQLite and Google Sheets on every attempt.

        Return signature is (bool, str) — unchanged from original — so
        existing login page callers require no updates.
        """
        email = email.strip().lower()
        user  = UserDAO.get_by_email(email)
        now   = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        if not user:
            return False, "Invalid credentials."

        # ── Lockout check ─────────────────────────────────────────────
        locked_until = getattr(user, "locked_until", None)
        if locked_until and str(locked_until) > now:
            return False, f"Account locked until {str(locked_until)[:19]} UTC."

        # ── Approval check ────────────────────────────────────────────
        if user.status != STATUS_APPROVED:
            return False, "Account not yet approved by admin."

        # ── Wrong password ────────────────────────────────────────────
        if not AuthService._verify_password(password, user.password_hash):
            failed_logins = getattr(user, "failed_logins", 0) or 0
            new_fails     = failed_logins + 1
            new_locked    = None

            if new_fails >= MAX_LOGIN_ATTEMPTS:
                new_locked = (
                    datetime.now(tz=timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
                ).strftime("%Y-%m-%dT%H:%M:%S")

            with get_db() as conn:
                conn.execute(
                    """UPDATE users
                       SET failed_logins = ?, locked_until = ?, updated_at = ?
                       WHERE id = ?""",
                    (new_fails, new_locked, now, user.id),
                )
                conn.commit()

            sheets_sync.push_user({
                "email":         email,
                "failed_logins": new_fails,
                "locked_until":  new_locked or "",
                "updated_at":    now,
            })

            if new_locked:
                return False, f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes."
            return False, "Invalid credentials."

        # ── Successful login ──────────────────────────────────────────
        with get_db() as conn:
            conn.execute(
                """UPDATE users
                   SET failed_logins = 0, locked_until = NULL,
                       last_login = ?, last_ip = ?, updated_at = ?
                   WHERE id = ?""",
                (now, ip, now, user.id),
            )
            conn.commit()

        sheets_sync.push_user({
            "email":         email,
            "failed_logins": 0,
            "locked_until":  "",
            "last_login":    now,
            "last_ip":       ip,
            "updated_at":    now,
        })
        sheets_sync.push_audit(
            actor_id    = user.id,
            actor_email = email,
            action      = "user_login",
            target      = email,
            ip_address  = ip,
        )

        return True, "Login successful."

    # ── Validation ─────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_registration(
        email: str, full_name: str, password: str
    ) -> Tuple[bool, str]:
        if not email or "@" not in email:
            return False, "Please enter a valid email address."
        if not full_name or len(full_name.strip()) < 2:
            return False, "Full name must be at least 2 characters."
        if len(password) < PASSWORD_MIN_LENGTH:
            return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter."
        if not re.search(r"\d", password):
            return False, "Password must contain at least one number."
        return True, ""

    # ── Password Hashing (PBKDF2-SHA256, 260k iterations) ─────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return f"{salt}:{key.hex()}"

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        try:
            salt, key_hex = stored_hash.split(":", 1)
            key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
            return secrets.compare_digest(key.hex(), key_hex)
        except Exception:
            return False

    # ── Admin Bootstrap ────────────────────────────────────────────────────────

    def _bootstrap_admin(self):
        """Create the default admin account if it does not yet exist."""
        if not UserDAO.get_by_email(ADMIN_EMAIL):
            pw_hash = self._hash_password(ADMIN_PASSWORD)
            UserDAO.create(
                ADMIN_EMAIL, ADMIN_NAME, pw_hash,
                role=ROLE_ADMIN, status=STATUS_APPROVED,
            )
            AuditDAO.log("admin_bootstrapped", target=ADMIN_EMAIL)
