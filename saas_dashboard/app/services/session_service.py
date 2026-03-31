"""
app/services/session_service.py  —  Streamlit session state management
"""

import streamlit as st
from datetime import datetime, timedelta
from config.settings import SESSION_EXPIRY_HOURS


class SessionService:

    SESSION_KEYS = {
        "authenticated": False,
        "user_id":       None,
        "user_email":    None,
        "user_name":     None,
        "user_role":     None,
        "user_status":   None,
        "current_page":  "login",
        "login_time":    None,
        "active_app":    None,
    }

    @classmethod
    def init_session(cls):
        """Initialize missing session keys with defaults."""
        for key, default in cls.SESSION_KEYS.items():
            if key not in st.session_state:
                st.session_state[key] = default

    @classmethod
    def login(cls, user):
        """Store authenticated user in session."""
        st.session_state.authenticated = True
        st.session_state.user_id       = user.id
        st.session_state.user_email    = user.email
        st.session_state.user_name     = user.full_name
        st.session_state.user_role     = user.role
        st.session_state.user_status   = user.status
        st.session_state.login_time    = datetime.utcnow().isoformat()
        st.session_state.current_page  = "admin_dashboard" if user.is_admin else "user_dashboard"

    @classmethod
    def logout(cls):
        """Clear all session state."""
        for key, default in cls.SESSION_KEYS.items():
            st.session_state[key] = default
        st.session_state.current_page = "login"

    @classmethod
    def is_session_valid(cls) -> bool:
        """Check session expiry."""
        if not st.session_state.get("authenticated"):
            return False
        login_time = st.session_state.get("login_time")
        if not login_time:
            return False
        expiry = datetime.fromisoformat(login_time) + timedelta(hours=SESSION_EXPIRY_HOURS)
        if datetime.utcnow() > expiry:
            cls.logout()
            return False
        return True

    @classmethod
    def navigate(cls, page: str):
        st.session_state.current_page = page

    @classmethod
    def set_active_app(cls, app_id: str):
        st.session_state.active_app   = app_id
        st.session_state.current_page = "app_runner"

    @classmethod
    def is_admin(cls) -> bool:
        return st.session_state.get("user_role") == "admin"

    @classmethod
    def current_user_id(cls):
        return st.session_state.get("user_id")
