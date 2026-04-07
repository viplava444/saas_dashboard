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
from app.models.database    import get_db
from app.models.database_migration import run_migrations
from app.services           import sheets_sync

st.set_page_config(
    page_title="Viplava Foundry | Enterprise Dashboard",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

def _bootstrap() -> None:
    '''
    Run once per server process (not once per browser session).
    Guards with st.session_state["_bootstrapped"] so Streamlit re-runs
    on every interaction don't repeat expensive startup work.
    '''
    if st.session_state.get("_bootstrapped"):
        return

    # 1. Apply schema migrations (idempotent — safe every boot)
    with get_db() as conn:
        run_migrations(conn)

    # 2. Initialise Sheets sync if secrets are present
    endpoint = st.secrets.get("SHEETS_ENDPOINT_URL", "")
    secret   = st.secrets.get("SHEETS_API_SECRET",   "")

    if endpoint and secret:
        sheets_sync.init(endpoint_url=endpoint, secret=secret)

        # 3. Cold-start restore: pull Sheets → seed local SQLite
        with get_db() as conn:
            counts = sheets_sync.restore_all(conn)

        total = sum(counts.values())
        if total:
            st.toast(
                f"☁️ Restored {counts.get('users', 0)} users, "
                f"{counts.get('user_app_access', 0)} app grants from cloud.",
                icon="✅",
            )
    else:
        st.toast("⚠️ Running without cloud persistence (Sheets not configured).",
                 icon="⚠️")

    st.session_state["_bootstrapped"] = True


_bootstrap()

def main():
    apply_global_styles()
    SessionService.init_session()
    auth = AuthService()
    route_page(auth)

if __name__ == "__main__":
    main()
