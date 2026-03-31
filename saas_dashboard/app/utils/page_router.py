"""
app/utils/page_router.py  —  Central routing table
"""

import streamlit as st
from app.services.session_service import SessionService


def route_page(auth):
    from app.pages.login        import render_login
    from app.pages.register     import render_register
    from app.pages.admin        import render_admin_dashboard
    from app.pages.user         import render_user_dashboard
    from app.pages.app_runner   import render_app_runner

    # Enforce session expiry
    if st.session_state.authenticated and not SessionService.is_session_valid():
        st.warning("⏱ Your session has expired. Please log in again.")
        st.stop()

    page = st.session_state.get("current_page", "login")

    # Public routes
    if page == "login":
        render_login(auth)
        return
    if page == "register":
        render_register(auth)
        return

    # Protected routes — must be authenticated
    if not st.session_state.get("authenticated"):
        SessionService.navigate("login")
        render_login(auth)
        return

    role = st.session_state.get("user_role")

    if page == "admin_dashboard" and role == "admin":
        render_admin_dashboard()
    elif page == "user_dashboard" and role == "user":
        render_user_dashboard()
    elif page == "app_runner":
        render_app_runner()
    else:
        # Fallback: redirect to appropriate home
        if role == "admin":
            SessionService.navigate("admin_dashboard")
            render_admin_dashboard()
        else:
            SessionService.navigate("user_dashboard")
            render_user_dashboard()
