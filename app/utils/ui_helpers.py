"""
app/utils/ui_helpers.py  —  Global styling, shared UI primitives
"""

import streamlit as st


# ─── Global CSS ───────────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
/* ── Google Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── CSS Variables ── */
:root {
    --bg-primary:    #0a0e1a;
    --bg-secondary:  #111827;
    --bg-card:       #1a2035;
    --accent-cyan:   #00d4ff;
    --accent-violet: #7c3aed;
    --accent-green:  #10b981;
    --accent-amber:  #f59e0b;
    --accent-red:    #ef4444;
    --text-primary:  #f0f4ff;
    --text-muted:    #6b7a9b;
    --border:        #1e2d4a;
    --radius:        12px;
    --font-main:     'Space Grotesk', sans-serif;
    --font-mono:     'JetBrains Mono', monospace;
}

/* ── Base resets ── */
html, body, [class*="css"] {
    font-family: var(--font-main) !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

/* ── Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem !important; max-width: 1400px !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}

/* ── Buttons ── */
.stButton > button {
    font-family: var(--font-main) !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 15px rgba(0, 212, 255, 0.2);
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stSelectbox > div > div > select {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
    font-family: var(--font-main) !important;
}
.stTextInput > div > div > input:focus {
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 0 2px rgba(0,212,255,0.15) !important;
}

/* ── Metric cards ── */
[data-testid="metric-container"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    padding: 1rem !important;
}

/* ── Expanders ── */
.streamlit-expanderHeader {
    font-weight: 600 !important;
    color: var(--text-primary) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ── Custom cards ── */
.nx-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.nx-card:hover { border-color: rgba(0,212,255,0.3); }

.nx-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.nx-badge-pending  { background: rgba(245,158,11,0.15);  color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }
.nx-badge-approved { background: rgba(16,185,129,0.15);  color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
.nx-badge-rejected { background: rgba(239,68,68,0.15);   color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
.nx-badge-revoked  { background: rgba(107,122,155,0.15); color: #6b7a9b; border: 1px solid rgba(107,122,155,0.3); }

.nx-app-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    cursor: pointer;
    transition: all 0.2s;
    text-align: center;
    height: 100%;
}
.nx-app-card:hover {
    border-color: var(--accent-cyan);
    box-shadow: 0 0 20px rgba(0,212,255,0.1);
    transform: translateY(-2px);
}

.nx-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 1.5rem 0;
}
</style>
"""


def apply_global_styles():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def status_badge(status: str) -> str:
    return f'<span class="nx-badge nx-badge-{status}">{status}</span>'


def card(content: str):
    st.markdown(f'<div class="nx-card">{content}</div>', unsafe_allow_html=True)


def section_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div style="margin-bottom:1.5rem">
        <h2 style="margin:0;font-weight:700;letter-spacing:-0.02em">{title}</h2>
        {"<p style='margin:0.25rem 0 0;color:var(--text-muted);font-size:0.9rem'>" + subtitle + "</p>" if subtitle else ""}
    </div>
    """, unsafe_allow_html=True)


def divider():
    st.markdown('<hr class="nx-divider">', unsafe_allow_html=True)
