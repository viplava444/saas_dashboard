"""
app/pages/user.py  —  User dashboard: app launcher
"""

import streamlit as st
from app.components.sidebar import render_sidebar
from app.services.session_service import SessionService
from app.services.admin_service import AdminService
from app.utils.ui_helpers import section_header, divider
from config.settings import AVAILABLE_APPS


def render_user_dashboard():
    render_sidebar()

    user_id = SessionService.current_user_id()
    name    = st.session_state.get("user_name", "there")
    svc     = AdminService()

    # ── Header ────────────────────────────────────────────────────────────────
    section_header(
        f"Welcome back, {name.split()[0]}",
        "Select an application to get started"
    )

    # ── Fetch accessible apps ─────────────────────────────────────────────────
    granted_ids = set(svc.get_user_app_access(user_id))
    all_apps    = [a for a in AVAILABLE_APPS if a["enabled"]]
    accessible  = [a for a in all_apps if a["id"] in granted_ids]
    locked      = [a for a in all_apps if a["id"] not in granted_ids]

    # ── Stats bar ─────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    col1.metric("Apps Available", len(accessible))
    col2.metric("Apps Locked",    len(locked))

    divider()

    # ── Accessible apps ───────────────────────────────────────────────────────
    if accessible:
        st.markdown("#### Your Applications")
        cols = st.columns(3)
        for i, app in enumerate(accessible):
            with cols[i % 3]:
                st.markdown(f"""
                <div class="nx-app-card">
                    <div style="font-size:2.5rem;margin-bottom:0.5rem">{app['icon']}</div>
                    <div style="font-weight:700;font-size:1rem;margin-bottom:0.25rem">{app['name']}</div>
                    <div style="color:var(--text-muted);font-size:0.8rem;margin-bottom:0.75rem">{app['description']}</div>
                    <span style="background:rgba(0,212,255,0.1);color:var(--accent-cyan);
                                 border:1px solid rgba(0,212,255,0.2);border-radius:20px;
                                 padding:2px 10px;font-size:0.7rem;font-weight:600">
                        {app['category']}
                    </span>
                </div>
                """, unsafe_allow_html=True)

                if st.button(f"Launch {app['name']}", key=f"launch_{app['id']}",
                             use_container_width=True, type="primary"):
                    SessionService.set_active_app(app["id"])
                    st.rerun()
    else:
        st.markdown("""
        <div style="text-align:center;padding:3rem;background:var(--bg-card);
                    border:1px dashed var(--border);border-radius:16px">
            <div style="font-size:3rem">🔐</div>
            <div style="font-weight:600;margin:0.75rem 0 0.25rem">No apps assigned yet</div>
            <div style="color:var(--text-muted);font-size:0.9rem">
                Contact your administrator to request access to applications.
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Locked apps ───────────────────────────────────────────────────────────
    if locked:
        divider()
        st.markdown("#### Other Available Apps")
        st.markdown(
            "<p style='color:var(--text-muted);font-size:0.85rem;margin-top:-0.5rem'>"
            "Contact your admin to request access.</p>",
            unsafe_allow_html=True
        )
        cols = st.columns(3)
        for i, app in enumerate(locked):
            with cols[i % 3]:
                st.markdown(f"""
                <div style="background:var(--bg-card);border:1px solid var(--border);
                            border-radius:12px;padding:1.25rem;text-align:center;
                            opacity:0.5;filter:grayscale(0.5)">
                    <div style="font-size:2.5rem;margin-bottom:0.5rem">{app['icon']}</div>
                    <div style="font-weight:700;font-size:1rem;margin-bottom:0.25rem">{app['name']}</div>
                    <div style="color:var(--text-muted);font-size:0.8rem;margin-bottom:0.75rem">{app['description']}</div>
                    <div style="font-size:0.8rem;color:var(--text-muted)">🔒 Access Required</div>
                </div>
                """, unsafe_allow_html=True)
