"""
app/pages/register.py  —  User registration page
"""

import streamlit as st
from app.services.session_service import SessionService
from app.pages.login import _render_auth_shell
from config.settings import APP_NAME, PASSWORD_MIN_LENGTH


def render_register(auth):
    _render_auth_shell()

    col1, col2, col3 = st.columns([1, 1.1, 1])
    with col2:
        st.markdown(f"""
        <div style="text-align:center;padding:2rem 0 1.5rem">
            <div style="font-size:2.2rem;font-weight:900;letter-spacing:-0.04em;
                        background:linear-gradient(135deg,#00d4ff,#7c3aed);
                        -webkit-background-clip:text;-webkit-text-fill-color:transparent">
                ⬡ {APP_NAME}
            </div>
            <div style="color:var(--text-muted);font-size:0.8rem;
                        letter-spacing:0.1em;text-transform:uppercase;margin-top:0.4rem">
                Request Access
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background:var(--bg-card);border:1px solid var(--border);
                    border-radius:16px;padding:2rem">
        """, unsafe_allow_html=True)

        st.markdown("#### Create your account")
        st.markdown(
            f"<p style='color:var(--text-muted);font-size:0.85rem;margin-top:-0.5rem'>"
            f"Accounts require admin approval before access is granted.</p>",
            unsafe_allow_html=True
        )

        with st.form("register_form", clear_on_submit=False):
            full_name = st.text_input("Full name", placeholder="Jane Doe")
            email     = st.text_input("Work email", placeholder="jane@company.com")

            st.markdown(f"""
            <div style="font-size:0.75rem;color:var(--text-muted);margin:0.25rem 0 0.5rem">
                Password requirements: {PASSWORD_MIN_LENGTH}+ characters, 
                one uppercase letter, one number
            </div>
            """, unsafe_allow_html=True)

            password  = st.text_input("Password", type="password", placeholder="••••••••")
            password2 = st.text_input("Confirm password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Request Access →", use_container_width=True, type="primary")

        if submitted:
            err = _validate_form(full_name, email, password, password2)
            if err:
                st.error(err)
            else:
                with st.spinner("Creating account…"):
                    ok, msg = auth.register(email.strip(), full_name.strip(), password)
                if ok:
                    st.success(f"✓ {msg}")
                    st.info("You'll receive access once an administrator approves your request.")
                    st.balloons()
                else:
                    st.error(msg)

        st.markdown('<hr style="border-color:var(--border);margin:1.5rem 0 1rem">', unsafe_allow_html=True)
        st.markdown(
            "<div style='text-align:center;color:var(--text-muted);font-size:0.88rem'>"
            "Already have an account?</div>",
            unsafe_allow_html=True
        )

        if st.button("← Back to Sign In", use_container_width=True):
            SessionService.navigate("login")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


def _validate_form(full_name, email, password, password2) -> str:
    """Returns error string or empty string."""
    if not full_name or not email or not password or not password2:
        return "All fields are required."
    if password != password2:
        return "Passwords do not match."
    return ""
