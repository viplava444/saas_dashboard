"""
app/services/admin_service.py  —  Admin workflow: approve/reject/access control
"""

from datetime import datetime, timezone
from typing import List

from app.models.audit import AuditDAO
from app.models.user import User, UserDAO
from app.services import sheets_sync
from config.settings import (
    AVAILABLE_APPS,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_REVOKED,
)


class AdminService:

    # ── Internal helper ────────────────────────────────────────────────────────

    @staticmethod
    def _push_user_to_sheets(user: User, admin_id: int = 0) -> str:
        """
        Push a user's current state to Google Sheets and return the
        admin's email for use in the audit push that follows.

        Best-effort — sheets_sync silently logs on failure.
        """
        if not user:
            return ""

        admin       = UserDAO.get_by_id(admin_id)
        actor_email = admin.email if admin else "admin"

        sheets_sync.push_user({
            "email":         user.email,
            "full_name":     user.full_name,
            "password_hash": user.password_hash,
            "role":          user.role,
            "status":        user.status,
            "failed_logins": getattr(user, "failed_logins", 0) or 0,
            "locked_until":  getattr(user, "locked_until",  "") or "",
            "last_login":    getattr(user, "last_login",    "") or "",
            "last_ip":       getattr(user, "last_ip",       "") or "",
        })

        return actor_email

    # ── User lifecycle ─────────────────────────────────────────────────────────

    @staticmethod
    def approve_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_APPROVED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_approved", actor_id=admin_id,
                     target=user.email if user else str(user_id))

        actor_email = AdminService._push_user_to_sheets(user, admin_id)
        sheets_sync.push_audit(
            actor_id    = admin_id,
            actor_email = actor_email,
            action      = "user_approved",
            target      = user.email if user else str(user_id),
        )

    @staticmethod
    def reject_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_REJECTED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_rejected", actor_id=admin_id,
                     target=user.email if user else str(user_id))

        actor_email = AdminService._push_user_to_sheets(user, admin_id)
        sheets_sync.push_audit(
            actor_id    = admin_id,
            actor_email = actor_email,
            action      = "user_rejected",
            target      = user.email if user else str(user_id),
        )

    @staticmethod
    def revoke_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_REVOKED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_revoked", actor_id=admin_id,
                     target=user.email if user else str(user_id))

        actor_email = AdminService._push_user_to_sheets(user, admin_id)
        sheets_sync.push_audit(
            actor_id    = admin_id,
            actor_email = actor_email,
            action      = "user_revoked",
            target      = user.email if user else str(user_id),
        )

    @staticmethod
    def reinstate_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_APPROVED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_reinstated", actor_id=admin_id,
                     target=user.email if user else str(user_id))

        actor_email = AdminService._push_user_to_sheets(user, admin_id)
        sheets_sync.push_audit(
            actor_id    = admin_id,
            actor_email = actor_email,
            action      = "user_reinstated",
            target      = user.email if user else str(user_id),
        )

    # ── App access ─────────────────────────────────────────────────────────────

    @staticmethod
    def grant_app_access(user_id: int, app_id: str, admin_id: int):
        UserDAO.grant_app(user_id, app_id, granted_by=admin_id)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("app_access_granted", actor_id=admin_id,
                     target=user.email if user else str(user_id),
                     detail=f"app={app_id}")

        sheets_sync.push_app_access(
            user_id    = user_id,
            app_id     = app_id,
            granted_by = admin_id,
        )
        actor_email = AdminService._push_user_to_sheets(user, admin_id)
        sheets_sync.push_audit(
            actor_id    = admin_id,
            actor_email = actor_email,
            action      = "app_access_granted",
            target      = user.email if user else str(user_id),
            detail      = f"app={app_id}",
        )

    @staticmethod
    def revoke_app_access(user_id: int, app_id: str, admin_id: int):
        UserDAO.revoke_app(user_id, app_id)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("app_access_revoked", actor_id=admin_id,
                     target=user.email if user else str(user_id),
                     detail=f"app={app_id}")

        revoked_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        sheets_sync.push_app_access(
            user_id    = user_id,
            app_id     = app_id,
            granted_by = admin_id,
            revoked_at = revoked_at,
        )
        actor_email = AdminService._push_user_to_sheets(user, admin_id)
        sheets_sync.push_audit(
            actor_id    = admin_id,
            actor_email = actor_email,
            action      = "app_access_revoked",
            target      = user.email if user else str(user_id),
            detail      = f"app={app_id}",
        )

    # ── Read-only queries (unchanged) ──────────────────────────────────────────

    @staticmethod
    def get_all_users() -> List[User]:
        return UserDAO.get_all(role="user")

    @staticmethod
    def get_pending_users() -> List[User]:
        return UserDAO.get_pending()

    @staticmethod
    def get_user_app_access(user_id: int) -> List[str]:
        return UserDAO.get_app_access(user_id)

    @staticmethod
    def get_available_apps() -> list:
        return [a for a in AVAILABLE_APPS if a["enabled"]]
