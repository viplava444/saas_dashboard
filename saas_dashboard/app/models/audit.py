"""
app/models/audit.py  —  Append-only audit trail
"""

from typing import Optional, List
from app.models.database import get_db


class AuditDAO:

    @staticmethod
    def log(action: str, actor_id: Optional[int] = None,
            target: Optional[str] = None, detail: Optional[str] = None,
            ip_address: Optional[str] = None):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO audit_log (actor_id, action, target, detail, ip_address)
                   VALUES (?, ?, ?, ?, ?)""",
                (actor_id, action, target, detail, ip_address)
            )

    @staticmethod
    def get_recent(limit: int = 100) -> List[dict]:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT a.*, u.email as actor_email
                   FROM audit_log a
                   LEFT JOIN users u ON a.actor_id = u.id
                   ORDER BY a.created_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
