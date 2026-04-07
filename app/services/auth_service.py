"""
app/services/auth_service.py  —  Authentication business logic
"""

import hashlib, secrets, re
from datetime import datetime, timedelta
from typing import Optional, Tuple
from datetime import datetime, timezone
from app.services import sheets_sync
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

   # Replace register():
    @staticmethod
    def register(email: str, full_name: str, password: str) -> tuple[bool, str]:
        email     = email.strip().lower()
        full_name = full_name.strip()

        if not email or not full_name or not password:
            return False, "All fields are required."
        if len(password) < 8:
            return False, "Password must be at least 8 characters."
        if UserDAO.get_by_email(email):
            return False, "An account with this email already exists."

        password_hash = AuthService._hash_password(password)
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        with get_db() as conn:
            cur = conn.execute(
                '''INSERT INTO users
                   (email, full_name, password_hash, role, status,
                    failed_logins, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (email, full_name, password_hash, "user", "pending", 0, now, now),
            )
            user_id = cur.lastrowid
            conn.commit()

        # Mirror to Sheets (best-effort)
        sheets_sync.push_user({
            "email":         email,
            "full_name":     full_name,
            "password_hash": password_hash,
            "role":          "user",
            "status":        "pending",
            "failed_logins": 0,
            "created_at":    now,
            "updated_at":    now,
        })
        sheets_sync.push_audit(
            actor_id=user_id, actor_email=email,
            action="user_registered", target=email,
        )

        return True, "Registration successful. Awaiting admin approval."

    # Replace login() to track last_login, last_ip, failed_logins:
    @staticmethod
    def login(email: str, password: str, ip: str = "") -> tuple[bool, str, dict | None]:
        '''
        Returns (success, message, user_info_dict | None).
        user_info_dict contains: id, email, full_name, role, status
        '''
        email = email.strip().lower()
        user  = UserDAO.get_by_email(email)
        now   = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        if not user:
            return False, "Invalid credentials.", None

        # Check lockout
        if user.locked_until and user.locked_until > now:
            return False, f"Account locked until {user.locked_until[:19]} UTC.", None

        if user.status != STATUS_APPROVED:
            return False, "Account not yet approved by admin.", None

        if not AuthService._verify_password(password, user.password_hash):
            new_fails = (user.failed_logins or 0) + 1
            locked_until = None
            if new_fails >= 5:
                from datetime import timedelta
                locked_until = (
                    datetime.now(tz=timezone.utc) + timedelta(minutes=15)
                ).strftime("%Y-%m-%dT%H:%M:%S")

            with get_db() as conn:
                conn.execute(
                    "UPDATE users SET failed_logins=?, locked_until=?, updated_at=? WHERE id=?",
                    (new_fails, locked_until, now, user.id),
                )
                conn.commit()

            sheets_sync.push_user({
                "email": email, "failed_logins": new_fails,
                "locked_until": locked_until or "", "updated_at": now,
            })
            msg = "Invalid credentials."
            if locked_until:
                msg = "Too many failed attempts. Account locked for 15 minutes."
            return False, msg, None

        # Successful login — reset counters, record metadata
        with get_db() as conn:
            conn.execute(
                "UPDATE users SET failed_logins=0, locked_until=NULL, "
                "last_login=?, last_ip=?, updated_at=? WHERE id=?",
                (now, ip, now, user.id),
            )
            conn.commit()

        sheets_sync.push_user({
            "email": email, "failed_logins": 0,
            "locked_until": "", "last_login": now,
            "last_ip": ip, "updated_at": now,
        })
        sheets_sync.push_audit(
            actor_id=user.id, actor_email=email,
            action="user_login", target=email, ip_address=ip,
        )

        return True, "Login successful.", {
            "id": user.id, "email": user.email,
            "full_name": user.full_name, "role": user.role,
        }
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
