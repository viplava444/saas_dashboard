"""
app/components/sidebar.py  —  Shared sidebar navigation
"""

import streamlit as st
from app.services.session_service import SessionService
from config.settings import APP_NAME, APP_VERSION


def render_sidebar():
    with st.sidebar:
        # ── Logo / Brand ──────────────────────────────────────────────────────
        st.markdown(f"""
        <div style="padding:1rem 0 1.5rem">
            <div style="font-size:1.6rem;font-weight:800;letter-spacing:-0.03em;
                        background:linear-gradient(135deg,#00d4ff,#7c3aed);
                        -webkit-background-clip:text;-webkit-text-fill-color:transparent">
                ⬡ {APP_NAME}
            </div>
            <div style="font-size:0.72rem;color:var(--text-muted);
                        letter-spacing:0.1em;text-transform:uppercase;margin-top:2px">
                Enterprise Platform v{APP_VERSION}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── User Info ─────────────────────────────────────────────────────────
        name  = st.session_state.get("user_name",  "User")
        email = st.session_state.get("user_email", "")
        role  = st.session_state.get("user_role",  "user")

        role_color = "#00d4ff" if role == "admin" else "#7c3aed"
        st.markdown(f"""
        <div style="background:var(--bg-card);border:1px solid var(--border);
                    border-radius:10px;padding:0.85rem;margin-bottom:1.5rem">
            <div style="font-weight:600;font-size:0.95rem">{name}</div>
            <div style="color:var(--text-muted);font-size:0.78rem;margin-top:2px">{email}</div>
            <div style="margin-top:0.5rem">
                <span style="background:rgba(0,0,0,0.3);color:{role_color};
                             border:1px solid {role_color}44;border-radius:20px;
                             padding:2px 10px;font-size:0.7rem;font-weight:700;
                             letter-spacing:0.08em;text-transform:uppercase">{role}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Navigation ────────────────────────────────────────────────────────
        st.markdown("**Navigation**")

        if role == "admin":
            _nav_btn("🏠  Dashboard",    "admin_dashboard")
            _nav_btn("👥  User Management", "admin_dashboard")   # handled via tabs
            _nav_btn("📋  Audit Log",    "audit_log")
        else:
            _nav_btn("🏠  My Dashboard", "user_dashboard")

        st.markdown('<hr style="border-color:var(--border);margin:1rem 0">', unsafe_allow_html=True)

        # ── Logout ────────────────────────────────────────────────────────────
        if st.button("⇠  Logout", use_container_width=True, type="secondary"):
            SessionService.logout()
            st.rerun()


def _nav_btn(label: str, page: str):
    current = st.session_state.get("current_page", "")
    is_active = current == page
    style = "primary" if is_active else "secondary"
    if st.button(label, use_container_width=True, type=style, key=f"nav_{page}_{label}"):
        SessionService.navigate(page)
        st.rerun()
