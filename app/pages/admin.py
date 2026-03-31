"""
app/pages/admin.py  —  Admin dashboard: approvals, user management, app access
"""

import streamlit as st
from app.components.sidebar import render_sidebar
from app.services.admin_service import AdminService
from app.services.session_service import SessionService
from app.models.audit import AuditDAO
from app.utils.ui_helpers import section_header, status_badge, divider
from config.settings import STATUS_APPROVED, STATUS_PENDING


def render_admin_dashboard():
    render_sidebar()

    admin_id = SessionService.current_user_id()
    svc      = AdminService()

    # ── Page header ───────────────────────────────────────────────────────────
    pending = svc.get_pending_users()
    section_header(
        "Admin Dashboard",
        f"{len(pending)} pending approval{'s' if len(pending) != 1 else ''} · "
        f"Full platform access"
    )

    # ── Top metrics ───────────────────────────────────────────────────────────
    all_users = svc.get_all_users()
    approved  = [u for u in all_users if u.status == STATUS_APPROVED]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Users",    len(all_users))
    col2.metric("Active Users",   len(approved))
    col3.metric("Pending Review", len(pending))
    col4.metric("Available Apps", len(svc.get_available_apps()))

    divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["🕐 Pending Approvals", "👥 User Management", "📋 Audit Log"])

    # ───────────────────────── TAB 1: Pending Approvals ──────────────────────
    with tab1:
        if not pending:
            st.info("✓ No pending requests — all caught up!")
        else:
            st.markdown(f"**{len(pending)} account{'s' if len(pending)!=1 else ''} awaiting review**")
            for user in pending:
                with st.container():
                    st.markdown(f"""
                    <div class="nx-card">
                        <div style="display:flex;justify-content:space-between;align-items:flex-start">
                            <div>
                                <div style="font-weight:600;font-size:1rem">{user.full_name}</div>
                                <div style="color:var(--text-muted);font-size:0.85rem">{user.email}</div>
                                <div style="margin-top:0.4rem;font-size:0.78rem;color:var(--text-muted)">
                                    Registered: {user.created_at[:10]}
                                </div>
                            </div>
                            <div>{status_badge("pending")}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    c1, c2, c3 = st.columns([1, 1, 4])
                    with c1:
                        if st.button("✓ Approve", key=f"approve_{user.id}", type="primary"):
                            svc.approve_user(user.id, admin_id)
                            st.success(f"✓ {user.full_name} approved.")
                            st.rerun()
                    with c2:
                        if st.button("✗ Reject", key=f"reject_{user.id}"):
                            svc.reject_user(user.id, admin_id)
                            st.warning(f"✗ {user.full_name} rejected.")
                            st.rerun()

    # ───────────────────────── TAB 2: User Management ────────────────────────
    with tab2:
        if not all_users:
            st.info("No registered users yet.")
        else:
            # Search / filter
            col_search, col_filter = st.columns([2, 1])
            search = col_search.text_input("🔍 Search users", placeholder="Name or email…", label_visibility="collapsed")
            status_filter = col_filter.selectbox("Filter by status", ["All", "approved", "pending", "rejected", "revoked"], label_visibility="collapsed")

            filtered = all_users
            if search:
                q = search.lower()
                filtered = [u for u in filtered if q in u.email.lower() or q in u.full_name.lower()]
            if status_filter != "All":
                filtered = [u for u in filtered if u.status == status_filter]

            st.markdown(f"Showing **{len(filtered)}** of **{len(all_users)}** users")
            divider()

            for user in filtered:
                _render_user_row(user, svc, admin_id)

    # ───────────────────────── TAB 3: Audit Log ──────────────────────────────
    with tab3:
        logs = AuditDAO.get_recent(100)
        if not logs:
            st.info("No audit events recorded yet.")
        else:
            st.markdown(f"**Last {len(logs)} events** (newest first)")
            for log in logs:
                actor = log.get("actor_email") or "system"
                st.markdown(f"""
                <div style="display:flex;gap:1rem;padding:0.6rem 0;
                            border-bottom:1px solid var(--border);font-size:0.83rem">
                    <span style="color:var(--text-muted);min-width:140px;font-family:var(--font-mono)">{log['created_at'][:19]}</span>
                    <span style="color:var(--accent-cyan);min-width:200px">{log['action']}</span>
                    <span style="color:var(--text-muted);min-width:160px">{actor}</span>
                    <span style="color:var(--text-primary)">{log.get('target','') or ''} {log.get('detail','') or ''}</span>
                </div>
                """, unsafe_allow_html=True)


# ── User row with app access manager ─────────────────────────────────────────

def _render_user_row(user, svc: AdminService, admin_id: int):
    with st.expander(
        f"{user.full_name}  ·  {user.email}  ·  {user.status.upper()}",
        expanded=False
    ):
        col_info, col_actions = st.columns([2, 1])

        with col_info:
            st.markdown(status_badge(user.status), unsafe_allow_html=True)
            st.markdown(f"""
            <div style="margin-top:0.75rem;font-size:0.85rem;color:var(--text-muted)">
                <div>📧 {user.email}</div>
                <div>📅 Joined: {user.created_at[:10]}</div>
            </div>
            """, unsafe_allow_html=True)

        with col_actions:
            if user.status == STATUS_APPROVED:
                if st.button("Revoke Access", key=f"revoke_{user.id}", use_container_width=True):
                    svc.revoke_user(user.id, admin_id)
                    st.warning("Access revoked.")
                    st.rerun()
            elif user.status in ("rejected", "revoked", "pending"):
                if st.button("Approve / Reinstate", key=f"reinstate_{user.id}",
                             use_container_width=True, type="primary"):
                    svc.reinstate_user(user.id, admin_id)
                    st.success("User approved.")
                    st.rerun()

        # ── App access control ────────────────────────────────────────────────
        if user.status == STATUS_APPROVED:
            st.markdown("---")
            st.markdown("**App Access Control**")

            apps           = svc.get_available_apps()
            current_access = set(svc.get_user_app_access(user.id))

            cols = st.columns(len(apps) if apps else 1)
            for i, app in enumerate(apps):
                has_access = app["id"] in current_access
                with cols[i]:
                    st.markdown(f"""
                    <div style="text-align:center;padding:0.5rem;
                                background:{'rgba(16,185,129,0.1)' if has_access else 'var(--bg-primary)'};
                                border:1px solid {'var(--accent-green)' if has_access else 'var(--border)'};
                                border-radius:8px;margin-bottom:0.5rem">
                        <div style="font-size:1.4rem">{app['icon']}</div>
                        <div style="font-size:0.78rem;font-weight:600">{app['name']}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    if has_access:
                        if st.button("Revoke", key=f"rev_app_{user.id}_{app['id']}", use_container_width=True):
                            svc.revoke_app_access(user.id, app["id"], admin_id)
                            st.rerun()
                    else:
                        if st.button("Grant", key=f"grant_app_{user.id}_{app['id']}",
                                     use_container_width=True, type="primary"):
                            svc.grant_app_access(user.id, app["id"], admin_id)
                            st.rerun()
