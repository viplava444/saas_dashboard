"""
app/services/admin_service.py  —  Admin workflow: approve/reject/access control
"""

from typing import List
from config.settings import STATUS_APPROVED, STATUS_REJECTED, STATUS_REVOKED, AVAILABLE_APPS
from app.models.user import UserDAO, User
from app.models.audit import AuditDAO
from app.services import sheets_sync

class AdminService:

    @staticmethod
    def approve_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_APPROVED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_approved", actor_id=admin_id,
                     target=user.email if user else str(user_id))

    @staticmethod
    def reject_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_REJECTED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_rejected", actor_id=admin_id,
                     target=user.email if user else str(user_id))

    @staticmethod
    def revoke_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_REVOKED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_revoked", actor_id=admin_id,
                     target=user.email if user else str(user_id))

    @staticmethod
    def reinstate_user(user_id: int, admin_id: int):
        UserDAO.update_status(user_id, STATUS_APPROVED)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("user_reinstated", actor_id=admin_id,
                     target=user.email if user else str(user_id))

    @staticmethod
    def grant_app_access(user_id: int, app_id: str, admin_id: int):
        UserDAO.grant_app(user_id, app_id, granted_by=admin_id)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("app_access_granted", actor_id=admin_id,
                     target=user.email if user else str(user_id),
                     detail=f"app={app_id}")

    @staticmethod
    def revoke_app_access(user_id: int, app_id: str, admin_id: int):
        UserDAO.revoke_app(user_id, app_id)
        user = UserDAO.get_by_id(user_id)
        AuditDAO.log("app_access_revoked", actor_id=admin_id,
                     target=user.email if user else str(user_id),
                     detail=f"app={app_id}")

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
