"""
Enterprise SaaS Dashboard - Main Entry Point
=============================================
Handles routing, session state initialization, and top-level auth flow.
"""

import streamlit as st
from app.services.auth_service import AuthService
from app.services.session_service import SessionService
from app.utils.page_router import route_page
from app.utils.ui_helpers import apply_global_styles

st.set_page_config(
    page_title="NexusOps | Enterprise Dashboard",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

def main():
    apply_global_styles()
    SessionService.init_session()
    auth = AuthService()
    route_page(auth)

if __name__ == "__main__":
    main()
