"""
app/services/sheets_client.py
──────────────────────────────
Typed HTTP client for the ViplavaForge Google Apps Script Web App.

One method per API action. Zero domain logic here — that lives in
sheets_sync.py. This layer only speaks raw dicts and raises
SheetsAPIError on any failure so callers can handle gracefully.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 12   # seconds — generous for Apps Script cold starts


class SheetsAPIError(Exception):
    """Network error or ok=false response from the Apps Script API."""


class SheetsClient:
    """
    HTTP client for the deployed Google Apps Script Web App.

    Parameters
    ----------
    endpoint_url : str
        Full /exec URL from Apps Script → Deploy → Manage deployments.
    secret : str
        Must match SHARED_SECRET in Code.gs exactly.
    """

    def __init__(self, endpoint_url: str, secret: str) -> None:
        if not endpoint_url or not secret:
            raise ValueError(
                "SHEETS_ENDPOINT_URL and SHEETS_API_SECRET must both be set "
                "in .streamlit/secrets.toml"
            )
        self._url    = endpoint_url.rstrip("/")
        self._secret = secret

    # ── Health ─────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if the API is reachable."""
        try:
            body = self._get(action="ping")
            return body.get("ok", False)
        except SheetsAPIError:
            return False

    # ── Users ──────────────────────────────────────────────────────────

    def get_all_users(self) -> list[dict]:
        return self._get(action="get_sheet", sheet="users").get("rows", [])

    def get_user_by_email(self, email: str) -> dict | None:
        return self._get(action="get_user_by_email", email=email).get("user")

    def get_user_by_id(self, user_id: int) -> dict | None:
        return self._get(action="get_user_by_id", id=str(user_id)).get("user")

    def upsert_user(self, **fields) -> dict:
        return self._post(action="upsert_user", **fields)

    def batch_upsert_users(self, users: list[dict]) -> int:
        result = self._post(action="batch_upsert_users", users=users)
        return result.get("processed", 0)

    # ── App access ─────────────────────────────────────────────────────

    def get_user_app_access(self, user_id: int) -> list[dict]:
        return self._get(
            action="get_user_app_access", user_id=str(user_id)
        ).get("rows", [])

    def get_all_app_access(self) -> list[dict]:
        return self._get(action="get_sheet", sheet="user_app_access").get("rows", [])

    def upsert_app_access(self, **fields) -> dict:
        return self._post(action="upsert_app_access", **fields)

    # ── Audit log ──────────────────────────────────────────────────────

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        return self._get(action="get_audit_log", limit=str(limit)).get("rows", [])

    def append_audit(
        self,
        *,
        actor_id: int | str,
        actor_email: str,
        audit_action: str,
        target: str = "",
        detail: str = "",
        ip_address: str = "",
        session_id: str = "",
        created_at: str = "",
    ) -> None:
        """Append one audit log row. Fire-and-forget — logs on failure."""
        try:
            self._post(
                action       = "append_audit",
                actor_id     = actor_id,
                actor_email  = actor_email,
                audit_action = audit_action,
                target       = target,
                detail       = detail,
                ip_address   = ip_address,
                session_id   = session_id,
                created_at   = created_at,
            )
        except SheetsAPIError as exc:
            logger.warning("Audit log push failed: %s", exc)

    # ── Sessions ───────────────────────────────────────────────────────

    def get_active_sessions(self, user_id: int) -> list[dict]:
        return self._get(
            action="get_active_sessions", user_id=str(user_id)
        ).get("rows", [])

    def upsert_session(self, **fields) -> dict:
        return self._post(action="upsert_session", **fields)

    def revoke_session(self, session_token: str) -> None:
        self._post(action="revoke_session", session_token=session_token)

    # ── App registry ───────────────────────────────────────────────────

    def get_app_registry(self) -> list[dict]:
        return self._get(action="get_sheet", sheet="app_registry").get("rows", [])

    def upsert_app_registry(self, **fields) -> dict:
        return self._post(action="upsert_app_registry", **fields)

    # ── Raw HTTP ───────────────────────────────────────────────────────

    def _get(self, action: str, **params) -> dict[str, Any]:
        try:
            resp = requests.get(
                self._url,
                params={"secret": self._secret, "action": action, **params},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()
        except requests.RequestException as exc:
            raise SheetsAPIError(f"Network error [{action}]: {exc}") from exc
        except ValueError as exc:
            raise SheetsAPIError(f"Bad JSON from API [{action}]: {exc}") from exc

        if not body.get("ok"):
            raise SheetsAPIError(
                f"API error [{action}]: {body.get('error', 'unknown')}"
            )
        return body

    def _post(self, action: str, **fields) -> dict[str, Any]:
        payload = {"secret": self._secret, "action": action, **fields}
        try:
            resp = requests.post(self._url, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
        except requests.RequestException as exc:
            raise SheetsAPIError(f"Network error [{action}]: {exc}") from exc
        except ValueError as exc:
            raise SheetsAPIError(f"Bad JSON from API [{action}]: {exc}") from exc

        if not body.get("ok"):
            raise SheetsAPIError(
                f"API error [{action}]: {body.get('error', 'unknown')}"
            )
        return body
