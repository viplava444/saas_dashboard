"""
app/services/auth_service.py  —  Authentication business logic
"""

import hashlib, secrets, re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from config.settings import (
    PASSWORD_MIN_LENGTH, MAX_LOGIN_ATTEMPTS,
    LOCKOUT_MINUTES, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME,
    ROLE_ADMIN, ROLE_USER, STATUS_APPROVED, STATUS_PENDING,
)
from app.models.database import init_db
from app.models.user import UserDAO, User
from app.models.audit import AuditDAO


class AuthService:

    def __init__(self):
        init_db()
        self._bootstrap_admin()

    # ── Public API ─────────────────────────────────────────────────────────────

    def register(self, email: str, full_name: str, password: str
                 ) -> Tuple[bool, str]:
        """Register a new user. Returns (success, message)."""
        valid, msg = self._validate_registration(email, full_name, password)
        if not valid:
            return False, msg

        if UserDAO.get_by_email(email):
            return False, "An account with this email already exists."

        pw_hash = self._hash_password(password)
        UserDAO.create(email, full_name, pw_hash, role=ROLE_USER, status=STATUS_PENDING)
        AuditDAO.log("user_registered", target=email)
        return True, "Registration successful. Awaiting admin approval."

    def login(self, email: str, password: str) -> Tuple[Optional[User], str]:
        """Authenticate user. Returns (User | None, message)."""
        user = UserDAO.get_by_email(email)
        if not user:
            return None, "Invalid email or password."

        # Lockout check
        if user.locked_until:
            lock_dt = datetime.fromisoformat(user.locked_until)
            if datetime.utcnow() < lock_dt:
                remaining = int((lock_dt - datetime.utcnow()).total_seconds() / 60) + 1
                return None, f"Account locked. Try again in {remaining} minute(s)."
            else:
                UserDAO.reset_failed_logins(user.id)
                user = UserDAO.get_by_id(user.id)

        # Password check
        if not self._verify_password(password, user.password_hash):
            UserDAO.increment_failed_login(user.id)
            updated = UserDAO.get_by_id(user.id)
            if updated.failed_logins >= MAX_LOGIN_ATTEMPTS:
                lockout_time = (
                    datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                ).isoformat()
                UserDAO.set_lockout(user.id, lockout_time)
                AuditDAO.log("account_locked", actor_id=user.id, target=user.email)
                return None, f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes."
            remaining = MAX_LOGIN_ATTEMPTS - updated.failed_logins
            return None, f"Invalid email or password. {remaining} attempt(s) remaining."

        # Status check
        if user.status == "pending":
            return None, "Your account is pending admin approval."
        if user.status in ("rejected", "revoked"):
            return None, "Your account access has been denied. Contact support."

        UserDAO.reset_failed_logins(user.id)
        AuditDAO.log("user_login", actor_id=user.id, target=user.email)
        return user, "Login successful."

    # ── Validation ─────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_registration(email: str, full_name: str, password: str
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

    # ── Password Hashing (PBKDF2-SHA256) ──────────────────────────────────────

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
        if not UserDAO.get_by_email(ADMIN_EMAIL):
            pw_hash = self._hash_password(ADMIN_PASSWORD)
            UserDAO.create(
                ADMIN_EMAIL, ADMIN_NAME, pw_hash,
                role=ROLE_ADMIN, status=STATUS_APPROVED
            )
            AuditDAO.log("admin_bootstrapped", target=ADMIN_EMAIL)
