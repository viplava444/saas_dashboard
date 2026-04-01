"""
app/apps/validation_js_generator.py
────────────────────────────────────
NexusOps micro-app — Validation JS Generator
Converts a survey-spec CSV / Excel into a Qualtrics-style
validationConfig JS object.

Drop-in contract: one public `render()` function, no module-level
Streamlit calls.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import streamlit as st

# ──────────────────────────────────────────────
# Constants & compiled patterns
# ──────────────────────────────────────────────

# Operator tables
_EVAL_OP: dict[str, str] = {
    "=": "==", "<=": "<=", "<": "<",
    ">=": ">=", ">": ">", "≤": "<=", "≥": ">=",
}
_REPL_OP: dict[str, str] = {
    "=": "=",
    "<=": r"\u2264", "≤": r"\u2264",
    ">=": r"\u2265", "≥": r"\u2265",
    "<": "<", ">": ">",
}

# Matches any operator token (longest-match first so <= beats <)
_OP_RE = re.compile(r"(<=|>=|≤|≥|=|<|>)")

# Columns whose names begin with "math rule" (case-insensitive)
_MATH_COL_RE = re.compile(r"^math\s*rule", re.IGNORECASE)


# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

class QidInfo(NamedTuple):
    base: str | None
    index: int | None
    is_text: bool


# ──────────────────────────────────────────────
# Pure helpers  (no Streamlit, fully testable)
# ──────────────────────────────────────────────

def _parse_qid(raw) -> QidInfo:
    """
    Parse a QID cell value into its components.

    Formats recognised
    ------------------
    ``QID123_TEXT``  → base="QID123", index=None, is_text=True
    ``QID123_4``     → base="QID123", index=4,    is_text=False
    ``QID123``       → base="QID123", index=None, is_text=False
    NaN / blank      → QidInfo(None, None, False)
    """
    if pd.isna(raw):
        return QidInfo(None, None, False)

    q = str(raw).strip()

    if q.upper().endswith("_TEXT"):
        return QidInfo(q.rsplit("_", 1)[0], None, True)

    if "_" in q:
        base, tail = q.rsplit("_", 1)
        if tail.isdigit():
            return QidInfo(base, int(tail), False)

    return QidInfo(q, None, False)


def _piped_token(info: QidInfo, *, for_eval: bool) -> str | None:
    """
    Build the Qualtrics piped-text expression for a QID.

    When *for_eval* is True the token is wrapped in
    ``protectPipedTextValue(…)`` so Qualtrics evaluates it numerically.
    """
    if info.base is None:
        return None

    if info.is_text:
        inner = f"${{q://{info.base}/ChoiceTextEntryValue}}"
    elif info.index:
        inner = f"${{q://{info.base}/ChoiceTextEntryValue/{info.index}}}"
    else:
        inner = f"${{q://{info.base}/ChoiceTextEntryValue}}"

    return f"protectPipedTextValue({inner})" if for_eval else inner


def _escape_js(s: str) -> str:
    r"""
    Escape *s* so it is safe inside a JS double-quoted string.

    Rules
    -----
    • ``"``  → ``\"``
    • ``\``  not followed by ``uXXXX`` → ``\\``
    • Everything else is left intact (real \uXXXX sequences survive).
    """
    s = s.replace("\\", "\\\\")        # escape backslashes first …
    s = re.sub(                         # … but restore real \uXXXX
        r"\\\\u([0-9A-Fa-f]{4})",
        r"\\u\1",
        s,
    )
    return s.replace('"', '\\"')


def _math_rule_columns(columns: pd.Index) -> list[str]:
    """Return column names whose heading begins with 'math rule'."""
    return [c for c in columns if _MATH_COL_RE.match(str(c))]


def _resolve_side(tokens: list[str], qmap: dict[str, QidInfo], *, for_eval: bool) -> str:
    """
    Turn a list of variable/literal tokens into a piped expression.

    Each token is either looked up in *qmap* (→ piped text) or kept as-is.
    Tokens are joined with `` + ``.
    """
    parts: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if tok in qmap:
            piped = _piped_token(qmap[tok], for_eval=for_eval)
            parts.append(piped if piped is not None else tok)
        else:
            parts.append(tok)
    return " + ".join(parts)


# ──────────────────────────────────────────────
# JS generation
# ──────────────────────────────────────────────

def build_validation_js(df: pd.DataFrame) -> tuple[str, list[str]]:
    """
    Parse *df* and return ``(js_source, warnings)``.

    The JS is a ``const validationConfig = { … };`` object literal.
    *warnings* is a list of human-readable messages for rows that were
    skipped or had parse issues.
    """
    warnings: list[str] = []

    # ── 1. Build QID map ──────────────────────────────────────────────
    qmap: dict[str, QidInfo] = {}

    qnum_col = "Q #" if "Q #" in df.columns else "Q#"
    if qnum_col not in df.columns:
        return "", ["No 'Q #' or 'Q#' column found — cannot proceed."]

    for _, row in df.iterrows():
        raw_qnum = row.get(qnum_col)
        if pd.isna(raw_qnum):
            continue
        qnum = str(raw_qnum).strip()
        qmap[qnum] = _parse_qid(row.get("QID"))

    math_cols = _math_rule_columns(df.columns)

    # ── 2. Build entries ──────────────────────────────────────────────
    entries: list[str] = []

    for _, row in df.iterrows():
        raw_qnum = row.get(qnum_col)
        if pd.isna(raw_qnum):
            continue

        qnum = str(raw_qnum).strip()
        qtext = "" if pd.isna(row.get("Questions")) else str(row["Questions"]).strip()

        rules = [
            str(row[c]).strip()
            for c in math_cols
            if pd.notna(row[c]) and str(row[c]).strip()
        ]

        for rule_idx, rule in enumerate(rules, start=1):

            # Split on the first operator token only
            m = _OP_RE.search(rule)
            if not m:
                warnings.append(f"Row {qnum}, rule {rule_idx}: no operator found — skipped.")
                continue

            op = m.group(1)
            lhs_raw = rule[: m.start()].strip()
            rhs_raw = rule[m.end() :].strip()

            eval_op = _EVAL_OP.get(op)
            repl_op = _REPL_OP.get(op)

            if not eval_op:
                warnings.append(f"Row {qnum}, rule {rule_idx}: unknown operator '{op}' — skipped.")
                continue

            # RHS may be a sum of variables/literals
            rhs_tokens = [t.strip() for t in rhs_raw.split("+")]

            lhs_eval = _resolve_side([lhs_raw], qmap, for_eval=True)
            lhs_repl = _resolve_side([lhs_raw], qmap, for_eval=False)
            rhs_eval = _resolve_side(rhs_tokens, qmap, for_eval=True)
            rhs_repl = _resolve_side(rhs_tokens, qmap, for_eval=False)

            piped_eval     = f"{lhs_eval} {eval_op} {rhs_eval}"
            piped_replaced = f"{lhs_repl} {repl_op} {rhs_repl}"

            key = qnum if len(rules) == 1 else f"{qnum}.{rule_idx}"

            entries.append(
                f'  "{key}": {{\n'
                f'    "Math Rule": {{\n'
                f'      displayVal: "{_escape_js(rule)}",\n'
                f'      pipedTextEval: "{_escape_js(piped_eval)}",\n'
                f'      pipedTextReplaced: "{_escape_js(piped_replaced)}"\n'
                f'    }},\n'
                f'    Questions: "{_escape_js(qtext)}"\n'
                f'  }}'
            )

    js = "const validationConfig = {\n" + ",\n".join(entries) + "\n};"
    return js, warnings


# ──────────────────────────────────────────────
# NexusOps entry-point
# ──────────────────────────────────────────────

def render() -> None:
    """NexusOps micro-app entry-point."""

    st.title("📊 Validation JS Generator")
    st.caption(
        "Upload a survey-spec CSV or Excel file to generate a Qualtrics "
        "``validationConfig`` JavaScript object."
    )

    # ── File upload ───────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "Upload your survey spec",
        type=["csv", "xlsx"],
        help="Must contain columns: Q # (or Q#), QID, Questions, and one or more 'Math Rule …' columns.",
    )

    if not uploaded:
        st.info("👆 Upload a CSV or Excel file to get started.")
        return

    # ── Parse file ────────────────────────────────────────────────────
    try:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)
    except Exception as exc:
        st.error(f"Could not read file: {exc}")
        return

    st.success(f"Loaded **{len(df)} rows** from `{uploaded.name}` ✅")

    with st.expander("Preview uploaded data", expanded=False):
        st.dataframe(df.head(10), use_container_width=True)

    # ── Generate JS ───────────────────────────────────────────────────
    with st.spinner("Generating JS…"):
        js_output, warnings = build_validation_js(df)

    # ── Warnings ──────────────────────────────────────────────────────
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} warning(s) — click to review", expanded=True):
            for w in warnings:
                st.warning(w)

    if not js_output:
        st.error("Nothing was generated. Check the warnings above.")
        return

    # ── Output ────────────────────────────────────────────────────────
    st.subheader("Generated Output")
    st.code(js_output, language="javascript")

    # ── Download ──────────────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".js")
    Path(tmp.name).write_text(js_output, encoding="utf-8")

    with open(tmp.name, "rb") as fh:
        st.download_button(
            label="📥 Download validation.js",
            data=fh,
            file_name="validation.js",
            mime="application/javascript",
        )
