"""
app/apps/survey_scrubber.py
────────────────────────────────────────────────────────────────────────────
NexusOps micro-app: Enterprise Survey QC Scrubber

Registration in config/settings.py:
    {
        "id":          "survey_scrubber",
        "name":        "Survey QC Scrubber",
        "description": "Config-driven survey data quality control, OE scrubbing & human-in-the-loop review.",
        "icon":        "🔬",
        "module_path": "app.apps.survey_scrubber",
        "category":    "Data Quality",
        "enabled":     True,
    }

Drop-in requirements (add to requirements.txt if not present):
    pandas>=2.0
    openpyxl>=3.1
    pyyaml>=6.0

Place the scrubber/ package and config/qc_config.yaml at the project root
(same level as main.py) so that imports resolve correctly.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# ── ensure scrubber package is importable from project root ─────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scrubber.config_loader import load_config
from scrubber.filter_engine import FilterEngine
from scrubber.input_handler import InputHandler, validate_required_columns
from scrubber.learning_store import LearningStore
from scrubber.output_generator import OutputGenerator
from scrubber.qc_engine import QCEngine, QCResult

logger = logging.getLogger("survey_scrubber_app")

# ────────────────────────────────────────────────────────────────────────────
# Session-state keys
# ────────────────────────────────────────────────────────────────────────────
_SK_CFG          = "sqc_config"
_SK_DF_RAW       = "sqc_df_raw"
_SK_DF_FILTERED  = "sqc_df_filtered"
_SK_RESULT       = "sqc_result"
_SK_STORE        = "sqc_learning_store"
_SK_REVIEW_IDX   = "sqc_review_idx"
_SK_RUN_DONE     = "sqc_run_done"
_SK_ACTIVE_TAB   = "sqc_active_tab"


def _ss(key, default=None):
    """Get or set a session-state value."""
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def _reset_run():
    for k in (_SK_DF_RAW, _SK_DF_FILTERED, _SK_RESULT, _SK_REVIEW_IDX, _SK_RUN_DONE):
        st.session_state.pop(k, None)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _load_default_cfg() -> dict:
    cfg_path = _PROJECT_ROOT / "config" / "qc_config.yaml"
    if cfg_path.exists():
        return load_config(cfg_path)
    return load_config()          # fallback to bundled defaults


def _df_to_excel_bytes(result: QCResult, gc_df: pd.DataFrame) -> bytes:
    """Generate an in-memory Excel workbook from QCResult and return bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        gc_df.to_excel(writer, sheet_name="Cleaned Data", index=False)
        if not result.ip_duplicates.empty:
            result.ip_duplicates.to_excel(writer, sheet_name="Duplicate IP", index=False)
        if not result.identifier_duplicates.empty:
            result.identifier_duplicates.to_excel(writer, sheet_name="Duplicate ID", index=False)
        for label, rpt in result.speeders.items():
            if not rpt.empty:
                safe_name = label[:31]   # Excel sheet name limit
                rpt.to_excel(writer, sheet_name=safe_name, index=False)
        if not result.oe_flags.empty:
            result.oe_flags.to_excel(writer, sheet_name="OE Flags", index=False)
    buf.seek(0)
    return buf.read()


def _metric_card(label: str, value: int, color: str = "#1e88e5") -> None:
    st.markdown(
        f"""
        <div style="background:{color}18;border-left:4px solid {color};
                    border-radius:6px;padding:12px 16px;margin-bottom:4px;">
            <div style="font-size:0.78rem;color:#888;text-transform:uppercase;
                        letter-spacing:.05em;">{label}</div>
            <div style="font-size:1.9rem;font-weight:700;color:{color};">{value:,}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_header(title: str, icon: str = "") -> None:
    st.markdown(
        f"<h4 style='margin-top:1.4rem;margin-bottom:.4rem'>{icon} {title}</h4>",
        unsafe_allow_html=True,
    )


# ────────────────────────────────────────────────────────────────────────────
# Tab renderers
# ────────────────────────────────────────────────────────────────────────────

def _tab_upload_run(cfg: dict) -> None:
    """Upload file + run pipeline."""
    _section_header("Upload Survey File", "📂")
    uploaded = st.file_uploader(
        "Supported formats: CSV · TSV · Excel (.xlsx / .xls)",
        type=["csv", "tsv", "xlsx", "xls"],
        key="sqc_uploader",
    )

    col1, col2 = st.columns(2)
    sheet_hint = col1.text_input(
        "Excel sheet (name or 0-based index)", value="0",
        help="Ignored for CSV/TSV files."
    )
    delim_hint = col2.text_input(
        "Delimiter override", value="",
        help="Leave blank for auto-detect. Use \\t for tab."
    )

    if uploaded is None:
        st.info("Upload a survey file to begin.")
        return

    st.success(f"File ready: **{uploaded.name}** ({uploaded.size:,} bytes)")

    run_clicked = st.button("▶ Run QC Pipeline", type="primary", use_container_width=True)

    if run_clicked:
        _reset_run()
        with st.spinner("Running QC pipeline…"):
            try:
                # Write upload to a temp file so InputHandler can detect extension
                suffix = Path(uploaded.name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.read())
                    tmp_path = tmp.name

                sheet_val: str | int = sheet_hint.strip()
                try:
                    sheet_val = int(sheet_val)
                except ValueError:
                    pass

                delim_val = delim_hint.strip().replace("\\t", "\t") or None

                handler = InputHandler(
                    filepath=tmp_path,
                    delimiter=delim_val,
                    sheet=sheet_val,
                )
                df = handler.load()
                st.session_state[_SK_DF_RAW] = df

                # Validate required columns
                cols = cfg["columns"]
                required = [
                    cols["response_id"], cols["ip"],
                    cols["duration"], cols["identifier"], cols["gc"],
                ]
                missing = validate_required_columns(df, required)
                if missing:
                    st.error(f"Missing required columns: **{', '.join(missing)}**")
                    st.info(
                        "Tip: map your column names in the **⚙ Config** tab "
                        "under *Column Name Mapping*."
                    )
                    return

                # GC filter
                gc_filtered = FilterEngine(cfg).apply(df)
                if gc_filtered.empty:
                    st.error("No rows passed the GC filter. Check your GC column/value in Config.")
                    return
                st.session_state[_SK_DF_FILTERED] = gc_filtered

                # QC checks
                result: QCResult = QCEngine(cfg).run(gc_filtered)
                st.session_state[_SK_RESULT] = result
                st.session_state[_SK_RUN_DONE] = True

            except Exception as exc:
                st.error(f"Pipeline error: {exc}")
                logger.exception("Pipeline failed")
                return

        st.success("Pipeline complete! View results in the **📊 Results** tab.")

    # Show raw preview if loaded
    if _SK_DF_RAW in st.session_state:
        with st.expander("Raw data preview (first 5 rows)"):
            st.dataframe(st.session_state[_SK_DF_RAW].head(), use_container_width=True)


def _tab_results(cfg: dict) -> None:
    """Display QC results with summary cards + data tables."""
    if _SK_RESULT not in st.session_state:
        st.info("Run the pipeline first (📂 Upload & Run tab).")
        return

    result: QCResult        = st.session_state[_SK_RESULT]
    gc_df:   pd.DataFrame   = st.session_state[_SK_DF_FILTERED]
    s                        = result.summary

    # ── KPI cards ──────────────────────────────────────────────────────
    _section_header("QC Summary", "📊")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("GC-filtered rows", s["total_gc_filtered_rows"], "#1e88e5")
    with c2:
        _metric_card("IP duplicates", s["ip_duplicate_rows"],
                     "#e53935" if s["ip_duplicate_rows"] else "#43a047")
    with c3:
        _metric_card("ID duplicates", s["identifier_duplicate_rows"],
                     "#e53935" if s["identifier_duplicate_rows"] else "#43a047")
    with c4:
        _metric_card("OE flagged", s["oe_flagged_rows"],
                     "#fb8c00" if s["oe_flagged_rows"] else "#43a047")

    if s.get("speeder_rows"):
        _section_header("Speeder Counts", "⏱")
        sp_cols = st.columns(len(s["speeder_rows"]))
        for idx, (label, count) in enumerate(s["speeder_rows"].items()):
            with sp_cols[idx]:
                _metric_card(label, count, "#8e24aa" if count else "#43a047")

    st.divider()

    # ── Detail tables ───────────────────────────────────────────────────
    if not result.ip_duplicates.empty:
        with st.expander(f"🔴 IP Duplicates ({len(result.ip_duplicates)} rows)", expanded=False):
            st.dataframe(result.ip_duplicates, use_container_width=True)

    if not result.identifier_duplicates.empty:
        with st.expander(f"🔴 Identifier Duplicates ({len(result.identifier_duplicates)} rows)", expanded=False):
            st.dataframe(result.identifier_duplicates, use_container_width=True)

    for label, rpt in result.speeders.items():
        if not rpt.empty:
            with st.expander(f"⏱ {label} ({len(rpt)} rows)", expanded=False):
                st.dataframe(rpt, use_container_width=True)

    if not result.oe_flags.empty:
        with st.expander(f"📝 OE Flags ({len(result.oe_flags)} rows)", expanded=False):
            st.dataframe(result.oe_flags, use_container_width=True)

    st.divider()
    _section_header("Download Results", "⬇️")

    dl1, dl2, dl3 = st.columns(3)

    with dl1:
        excel_bytes = _df_to_excel_bytes(result, gc_df)
        st.download_button(
            "📥 Download QC Report (.xlsx)",
            data=excel_bytes,
            file_name="survey_QC_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with dl2:
        csv_bytes = gc_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "📥 Download Cleaned CSV",
            data=csv_bytes,
            file_name="survey_cleaned.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with dl3:
        summary_json = json.dumps(s, indent=2).encode("utf-8")
        st.download_button(
            "📥 Download Summary JSON",
            data=summary_json,
            file_name="qc_summary.json",
            mime="application/json",
            use_container_width=True,
        )


def _tab_oe_review(cfg: dict) -> None:
    """Human-in-the-loop OE review panel."""
    if _SK_RESULT not in st.session_state:
        st.info("Run the pipeline first (📂 Upload & Run tab).")
        return

    result: QCResult = st.session_state[_SK_RESULT]
    store: LearningStore = st.session_state.get(_SK_STORE)

    if store is None or not store.enabled:
        st.warning("Learning store is disabled. Enable it in the ⚙ Config tab.")
        return

    oe_flags = result.oe_flags
    if oe_flags.empty:
        st.success("✅ No OE flags to review — all open-ended responses passed.")
        return

    total  = len(oe_flags)
    idx    = _ss(_SK_REVIEW_IDX, 0)
    idx    = min(idx, total - 1)

    # Progress bar
    st.progress((idx + 1) / total, text=f"Reviewing {idx + 1} of {total} flagged responses")

    row = oe_flags.iloc[idx]

    # Response card
    st.markdown(
        f"""
        <div style="border:1px solid #ddd;border-radius:8px;padding:16px;
                    background:#fafafa;margin-bottom:12px;">
            <div style="display:flex;gap:16px;margin-bottom:8px;">
                <span style="font-size:.8rem;color:#666;">Response ID</span>
                <code style="font-size:.85rem;">{row['ResponseId']}</code>
                <span style="font-size:.8rem;color:#666;">Column</span>
                <code style="font-size:.85rem;">{row['Column']}</code>
            </div>
            <div style="font-size:.8rem;color:#e53935;margin-bottom:6px;">
                Flags: <strong>{row['Flags']}</strong>
            </div>
            <div style="font-size:1rem;padding:8px;background:#fff;
                        border-radius:4px;border:1px solid #eee;">
                {str(row['Response'])[:500]}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)

    def _record(label: str):
        store.record_feedback(
            response_id=str(row["ResponseId"]),
            column=str(row["Column"]),
            text=str(row["Response"]),
            label=label,
        )
        st.session_state[_SK_REVIEW_IDX] = min(idx + 1, total - 1)

    with col1:
        if st.button("✅ Valid", use_container_width=True, key=f"oe_v_{idx}"):
            _record("valid")
            st.rerun()
    with col2:
        if st.button("❌ Invalid", use_container_width=True, key=f"oe_i_{idx}"):
            _record("invalid")
            st.rerun()
    with col3:
        if st.button("🔶 Borderline", use_container_width=True, key=f"oe_b_{idx}"):
            _record("borderline")
            st.rerun()
    with col4:
        if st.button("⏭ Skip", use_container_width=True, key=f"oe_s_{idx}"):
            st.session_state[_SK_REVIEW_IDX] = min(idx + 1, total - 1)
            st.rerun()

    # Navigation
    nav1, nav2 = st.columns(2)
    with nav1:
        if st.button("← Previous", disabled=(idx == 0), use_container_width=True):
            st.session_state[_SK_REVIEW_IDX] = max(0, idx - 1)
            st.rerun()
    with nav2:
        if st.button("Next →", disabled=(idx >= total - 1), use_container_width=True):
            st.session_state[_SK_REVIEW_IDX] = min(total - 1, idx + 1)
            st.rerun()


def _tab_learning(cfg: dict) -> None:
    """View + manage learning store: auto-rules, feedback history, import/export."""
    store: LearningStore | None = st.session_state.get(_SK_STORE)

    if store is None or not store.enabled:
        st.warning("Learning store is disabled. Enable it in the ⚙ Config tab.")
        return

    # ── Auto-promoted rules ─────────────────────────────────────────────
    _section_header("Auto-Promoted Reject Rules", "🤖")
    rules = store.get_auto_rules()
    if rules:
        rules_df = pd.DataFrame(rules)
        st.dataframe(rules_df, use_container_width=True)

        st.markdown("**Demote a rule:**")
        pattern_to_demote = st.text_input(
            "Enter exact pattern to remove", key="demote_pattern"
        )
        if st.button("🗑 Demote Rule", key="demote_btn"):
            if pattern_to_demote:
                removed = store.demote_rule(pattern_to_demote)
                if removed:
                    st.success(f"Rule removed: `{pattern_to_demote}`")
                else:
                    st.warning("Pattern not found in rules.")
                st.rerun()
    else:
        st.info(
            "No auto-promoted rules yet. Rules are promoted automatically "
            f"after **{cfg.get('learning', {}).get('auto_promote_threshold', 5)}** "
            "invalid labels for the same response text."
        )

    st.divider()

    # ── Export / Import ─────────────────────────────────────────────────
    _section_header("Export / Import Rules", "🔄")
    exp_col, imp_col = st.columns(2)

    with exp_col:
        st.markdown("**Export rules as JSON**")
        if rules:
            export_bytes = json.dumps(rules, indent=2).encode("utf-8")
            st.download_button(
                "⬇ Export Rules",
                data=export_bytes,
                file_name="auto_reject_rules.json",
                mime="application/json",
                use_container_width=True,
            )
        else:
            st.caption("No rules to export yet.")

    with imp_col:
        st.markdown("**Import rules from JSON**")
        imp_file = st.file_uploader(
            "Upload rules JSON", type=["json"], key="rules_import"
        )
        if imp_file and st.button("⬆ Import Rules", use_container_width=True):
            try:
                incoming = json.loads(imp_file.read())
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".json", mode="w", encoding="utf-8"
                ) as tf:
                    json.dump(incoming, tf)
                    tf_path = tf.name
                added = store.import_rules(tf_path)
                st.success(f"Imported **{added}** new rule(s).")
                st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")


def _tab_config(cfg: dict) -> dict:
    """
    Live config editor.
    Returns (potentially modified) cfg dict.
    Modifications are stored in session state and used for the next run.
    """
    _section_header("Column Name Mapping", "🗂")
    st.caption("Map logical names to your survey file's actual column headers.")

    cols_cfg = cfg.get("columns", {})
    new_cols = {}
    col_pairs = list(cols_cfg.items())
    grid_cols = st.columns(3)
    for i, (key, val) in enumerate(col_pairs):
        with grid_cols[i % 3]:
            new_cols[key] = st.text_input(key, value=val, key=f"col_{key}")
    cfg["columns"] = new_cols

    st.divider()
    _section_header("GC Filter", "🔍")

    gc = cfg.get("gc_filter", {})
    fc1, fc2, fc3 = st.columns(3)
    gc["column"]   = fc1.text_input("GC Column",   value=gc.get("column", "gc"))
    gc["operator"] = fc2.selectbox(
        "Operator",
        ["=", "!=", ">", ">=", "<", "<=", "in", "not_in"],
        index=["=", "!=", ">", ">=", "<", "<=", "in", "not_in"].index(
            gc.get("operator", "=")
        ),
    )
    gc_val_raw = gc.get("value", 1)
    gc["value"]    = fc3.text_input(
        "Value (use comma-separated list for in/not_in)",
        value=str(gc_val_raw) if not isinstance(gc_val_raw, list)
              else ", ".join(str(v) for v in gc_val_raw),
    )
    # Parse list values
    if gc["operator"] in ("in", "not_in"):
        gc["value"] = [v.strip() for v in str(gc["value"]).split(",")]
    else:
        try:
            gc["value"] = int(gc["value"])
        except ValueError:
            pass
    cfg["gc_filter"] = gc

    st.divider()
    _section_header("Speeder Thresholds", "⏱")

    speeder_list = cfg.get("speeder_thresholds", [])
    st.caption("Each threshold produces a separate sheet in the QC report.")
    new_speeders = []
    for i, sp in enumerate(speeder_list):
        sc1, sc2, sc3 = st.columns([3, 2, 1])
        label = sc1.text_input("Label", value=sp.get("label", ""), key=f"sp_lbl_{i}")
        thr   = sc2.number_input(
            "Threshold (min)", value=float(sp.get("threshold_minutes", 5.0)),
            min_value=0.1, step=0.5, key=f"sp_thr_{i}"
        )
        remove = sc3.checkbox("Remove", key=f"sp_rm_{i}")
        if not remove:
            new_speeders.append({"label": label, "threshold_minutes": thr})

    if st.button("➕ Add Speeder Threshold"):
        new_speeders.append({"label": "Speeder - <=X min", "threshold_minutes": 5.0})

    cfg["speeder_thresholds"] = new_speeders

    st.divider()
    _section_header("Open-Ended (OE) Scrubbing", "📝")

    oe = cfg.get("oe_scrubbing", {})
    oe["enabled"]         = st.toggle("Enable OE scrubbing", value=oe.get("enabled", True))
    if oe["enabled"]:
        oe["mode"]        = st.radio("Column selection mode", ["auto", "list"],
                                     index=0 if oe.get("mode", "auto") == "auto" else 1,
                                     horizontal=True)
        if oe["mode"] == "list":
            cols_raw = st.text_input(
                "Column names (comma-separated)",
                value=", ".join(oe.get("columns", [])),
            )
            oe["columns"] = [c.strip() for c in cols_raw.split(",") if c.strip()]

        oe_c1, oe_c2 = st.columns(2)
        oe["min_length"] = oe_c1.number_input("Min length (chars)", value=int(oe.get("min_length", 3)), min_value=1)
        oe["max_length"] = oe_c2.number_input("Max length (chars)", value=int(oe.get("max_length", 5000)), min_value=10)

        oe_c3, oe_c4 = st.columns(2)
        oe["profanity_filter"] = oe_c3.toggle("Profanity filter", value=oe.get("profanity_filter", True))
        oe["gibberish_check"]  = oe_c4.toggle("Gibberish check",  value=oe.get("gibberish_check", True))

        if oe["gibberish_check"]:
            oe["gibberish_unique_char_ratio"] = st.slider(
                "Gibberish unique-char ratio threshold",
                min_value=0.5, max_value=1.0,
                value=float(oe.get("gibberish_unique_char_ratio", 0.85)),
                step=0.01,
                help="Higher = stricter. Responses where unique chars / total chars exceeds this are flagged.",
            )
    cfg["oe_scrubbing"] = oe

    st.divider()
    _section_header("Duplicate Detection", "🔁")
    dup = cfg.get("duplicates", {})
    dc1, dc2 = st.columns(2)
    dup["check_ip"]         = dc1.toggle("Check IP duplicates",         value=dup.get("check_ip", True))
    dup["check_identifier"] = dc2.toggle("Check identifier duplicates", value=dup.get("check_identifier", True))
    cfg["duplicates"] = dup

    st.divider()
    _section_header("Learning Store", "🧠")
    lrn = cfg.get("learning", {})
    lrn["enabled"]               = st.toggle("Enable learning store", value=lrn.get("enabled", True))
    lrn["auto_promote_threshold"] = st.number_input(
        "Auto-promote threshold (# invalid labels needed to create a rule)",
        value=int(lrn.get("auto_promote_threshold", 5)),
        min_value=1,
    )
    cfg["learning"] = lrn

    st.divider()
    _section_header("Export Config", "💾")
    export_yaml = yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
    st.download_button(
        "⬇ Download current config as YAML",
        data=export_yaml.encode("utf-8"),
        file_name="qc_config_custom.yaml",
        mime="text/yaml",
        use_container_width=True,
    )

    return cfg


# ────────────────────────────────────────────────────────────────────────────
# Main render() — NexusOps entry point
# ────────────────────────────────────────────────────────────────────────────

def render() -> None:
    st.title("🔬 Survey QC Scrubber")
    st.caption(
        "Config-driven survey data quality control — "
        "duplicates · speeders · open-ended text · human-in-the-loop review"
    )

    # ── Load / initialise config ─────────────────────────────────────────
    if _SK_CFG not in st.session_state:
        st.session_state[_SK_CFG] = _load_default_cfg()
    cfg: dict = st.session_state[_SK_CFG]

    # ── Initialise learning store whenever cfg changes ───────────────────
    store_key = json.dumps(cfg.get("learning", {}), sort_keys=True)
    if (
        _SK_STORE not in st.session_state
        or getattr(st.session_state.get(_SK_STORE), "_store_key", None) != store_key
    ):
        store = LearningStore(cfg)
        store._store_key = store_key          # type: ignore[attr-defined]
        st.session_state[_SK_STORE] = store

    # ── Upload custom config ─────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙ Config Override")
        cfg_upload = st.file_uploader(
            "Upload YAML config override", type=["yaml", "yml"],
            key="cfg_uploader"
        )
        if cfg_upload is not None:
            try:
                user_overrides = yaml.safe_load(cfg_upload.read())
                from scrubber.config_loader import _deep_merge
                st.session_state[_SK_CFG] = _deep_merge(_load_default_cfg(), user_overrides)
                _reset_run()
                st.success("Config override applied.")
                st.rerun()
            except Exception as exc:
                st.error(f"Invalid YAML: {exc}")

        if st.button("🔄 Reset to defaults", use_container_width=True):
            st.session_state[_SK_CFG] = _load_default_cfg()
            _reset_run()
            st.rerun()

    # ── Tabs ─────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "📂 Upload & Run",
        "📊 Results",
        "📝 OE Review",
        "🧠 Learning Store",
        "⚙ Config",
    ])

    with tabs[0]:
        _tab_upload_run(cfg)

    with tabs[1]:
        _tab_results(cfg)

    with tabs[2]:
        _tab_oe_review(cfg)

    with tabs[3]:
        _tab_learning(cfg)

    with tabs[4]:
        updated_cfg = _tab_config(cfg)
        # Persist any changes made in the config tab
        if updated_cfg is not cfg:
            st.session_state[_SK_CFG] = updated_cfg
