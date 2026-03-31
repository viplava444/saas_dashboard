"""
app/apps/data_explorer.py  —  Sample micro-app: CSV / Excel data profiler
Every app must expose a render() function — that's the only contract.
"""

import streamlit as st
import io


def render():
    st.markdown("Upload a CSV or Excel file to get an instant data profile.")

    uploaded = st.file_uploader(
        "Drop your file here",
        type=["csv", "xlsx", "xls"],
        help="Max 200 MB"
    )

    if not uploaded:
        _show_empty_state()
        return

    try:
        import pandas as pd
    except ImportError:
        st.error("pandas is required. Run: `pip install pandas openpyxl`")
        return

    with st.spinner("Profiling dataset…"):
        if uploaded.name.endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)

    st.success(f"✓ Loaded **{uploaded.name}** — {df.shape[0]:,} rows × {df.shape[1]} columns")

    tab1, tab2, tab3 = st.tabs(["📊 Overview", "🔍 Preview", "📈 Stats"])

    with tab1:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Rows",    f"{df.shape[0]:,}")
        col2.metric("Columns", df.shape[1])
        col3.metric("Missing values", int(df.isnull().sum().sum()))
        col4.metric("Duplicate rows", int(df.duplicated().sum()))

        st.markdown("#### Column Summary")
        col_info = []
        for col in df.columns:
            col_info.append({
                "Column":   col,
                "Type":     str(df[col].dtype),
                "Non-null": df[col].notna().sum(),
                "Nulls":    df[col].isna().sum(),
                "Unique":   df[col].nunique(),
            })
        import pandas as pd
        st.dataframe(pd.DataFrame(col_info), use_container_width=True, hide_index=True)

    with tab2:
        n = st.slider("Rows to preview", 5, min(100, len(df)), 10)
        st.dataframe(df.head(n), use_container_width=True)

    with tab3:
        numeric = df.select_dtypes(include="number")
        if numeric.empty:
            st.info("No numeric columns found.")
        else:
            st.dataframe(numeric.describe().round(3), use_container_width=True)


def _show_empty_state():
    st.markdown("""
    <div style="text-align:center;padding:3rem;background:var(--bg-card);
                border:1px dashed var(--border);border-radius:12px;margin-top:1rem">
        <div style="font-size:3rem">📂</div>
        <div style="font-weight:600;margin:0.75rem 0 0.25rem">No file selected</div>
        <div style="color:var(--text-muted);font-size:0.88rem">
            Supports CSV, XLSX, XLS up to 200 MB
        </div>
    </div>
    """, unsafe_allow_html=True)
