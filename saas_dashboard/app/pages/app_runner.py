"""
app/pages/app_runner.py  —  Dynamically loads and sandboxes micro-apps
"""

import importlib
import streamlit as st
from app.components.sidebar import render_sidebar
from app.services.session_service import SessionService
from app.services.admin_service import AdminService
from config.settings import AVAILABLE_APPS


def render_app_runner():
    render_sidebar()

    app_id  = st.session_state.get("active_app")
    user_id = SessionService.current_user_id()
    role    = st.session_state.get("user_role")

    if not app_id:
        st.error("No app selected.")
        if st.button("← Back to Dashboard"):
            _go_home(role)
        return

    # ── Access guard (re-verified server-side) ────────────────────────────────
    if role != "admin":
        granted = AdminService.get_user_app_access(user_id)
        if app_id not in granted:
            st.error("🔐 You don't have access to this application.")
            if st.button("← Back to Dashboard"):
                _go_home(role)
            return

    # ── Resolve app config ─────────────────────────────────────────────────────
    app_cfg = next((a for a in AVAILABLE_APPS if a["id"] == app_id), None)
    if not app_cfg:
        st.error(f"App '{app_id}' is not registered.")
        return

    # ── Back button ───────────────────────────────────────────────────────────
    col1, col2 = st.columns([0.1, 0.9])
    with col1:
        if st.button("←", help="Back to dashboard"):
            _go_home(role)

    # ── App header ────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="margin-bottom:1.5rem">
        <div style="display:flex;align-items:center;gap:0.75rem">
            <span style="font-size:2rem">{app_cfg['icon']}</span>
            <div>
                <div style="font-size:1.4rem;font-weight:700">{app_cfg['name']}</div>
                <div style="color:var(--text-muted);font-size:0.85rem">{app_cfg['description']}</div>
            </div>
        </div>
    </div>
    <hr style="border-color:var(--border)">
    """, unsafe_allow_html=True)

    # ── Dynamic module load ────────────────────────────────────────────────────
    try:
        module = importlib.import_module(app_cfg["module_path"])
        module.render()
    except ModuleNotFoundError:
        _render_placeholder(app_cfg)
    except Exception as e:
        st.error(f"Error loading app: {e}")


def _go_home(role):
    page = "admin_dashboard" if role == "admin" else "user_dashboard"
    SessionService.navigate(page)
    st.session_state.active_app = None
    st.rerun()


def _render_placeholder(app_cfg):
    st.markdown(f"""
    <div style="text-align:center;padding:4rem;background:var(--bg-card);
                border:1px dashed var(--border);border-radius:16px;margin-top:2rem">
        <div style="font-size:3.5rem;margin-bottom:1rem">{app_cfg['icon']}</div>
        <div style="font-size:1.2rem;font-weight:700;margin-bottom:0.5rem">
            {app_cfg['name']} — Coming Soon
        </div>
        <div style="color:var(--text-muted);max-width:400px;margin:0 auto;font-size:0.9rem">
            This application module is registered but not yet implemented.
            Drop your code in <code>app/apps/{app_cfg['id']}.py</code> 
            with a <code>render()</code> function to activate it.
        </div>
    </div>
    """, unsafe_allow_html=True)
