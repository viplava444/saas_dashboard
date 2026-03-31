"""
app/pages/login.py  —  Login page
"""

import streamlit as st
from app.services.session_service import SessionService
from config.settings import APP_NAME, APP_TAGLINE


def render_login(auth):
    _render_auth_shell()

    col1, col2, col3 = st.columns([1, 1.1, 1])
    with col2:
        st.markdown(f"""
        <div style="text-align:center;padding:2rem 0 1.5rem">
            <div style="font-size:2.8rem;font-weight:900;letter-spacing:-0.04em;
                        background:linear-gradient(135deg,#00d4ff 0%,#7c3aed 100%);
                        -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                        line-height:1">⬡ {APP_NAME}</div>
            <div style="color:var(--text-muted);font-size:0.85rem;
                        letter-spacing:0.12em;text-transform:uppercase;margin-top:0.5rem">
                {APP_TAGLINE}
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background:var(--bg-card);border:1px solid var(--border);
                    border-radius:16px;padding:2rem">
        """, unsafe_allow_html=True)

        st.markdown("#### Sign in to your account")

        with st.form("login_form", clear_on_submit=False):
            email    = st.text_input("Email address", placeholder="you@company.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign In →", use_container_width=True, type="primary")

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
            else:
                with st.spinner("Authenticating…"):
                    user, msg = auth.login(email.strip(), password)
                if user:
                    SessionService.login(user)
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        st.markdown('<hr style="border-color:var(--border);margin:1.5rem 0 1rem">', unsafe_allow_html=True)
        st.markdown(
            "<div style='text-align:center;color:var(--text-muted);font-size:0.88rem'>"
            "Don't have an account?</div>",
            unsafe_allow_html=True
        )

        if st.button("Create account", use_container_width=True):
            SessionService.navigate("register")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

        # Footer hint
        st.markdown("""
        <div style="text-align:center;margin-top:1.5rem;color:var(--text-muted);font-size:0.75rem">
            Protected by enterprise-grade security · Session expires in 8 hours
        </div>
        """, unsafe_allow_html=True)


def _render_auth_shell():
    """Background decoration for auth pages."""
    st.markdown("""
    <style>
    .block-container { max-width: 100% !important; padding: 0 !important; }
    </style>
    <div style="position:fixed;top:0;left:0;right:0;bottom:0;z-index:-1;
                background:radial-gradient(ellipse at 20% 50%, rgba(124,58,237,0.08) 0%, transparent 60%),
                           radial-gradient(ellipse at 80% 20%, rgba(0,212,255,0.06) 0%, transparent 50%),
                           #0a0e1a">
    </div>
    """, unsafe_allow_html=True)
