"""
scrubber/qc_engine.py
─────────────────────
Core quality-control logic.

Produces structured report DataFrames for:
  • IP address duplicates
  • Identifier duplicates
  • Speeders (configurable thresholds)
  • Open-ended text (OE) quality issues

All report DataFrames follow a consistent contract:
  - First column is always ``ResponseId``
  - Second column is the flagged value or score
  - An optional ``Flag`` column carries the reason string

This makes the output predictable for downstream formatters regardless
of which checks are run.
"""

from __future__ import annotations

import logging
import math
import re
import string
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lightweight profanity word-list (extend as needed; no external dependency)
# ---------------------------------------------------------------------------
_PROFANITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b" + w + r"\b", re.IGNORECASE)
    for w in [
        "fuck", "shit", "ass", "bitch", "bastard", "cunt", "dick",
        "damn", "crap", "piss",
    ]
]


@dataclass
class QCResult:
    """Holds all report DataFrames produced by one QC run."""
    ip_duplicates:          pd.DataFrame = field(default_factory=pd.DataFrame)
    identifier_duplicates:  pd.DataFrame = field(default_factory=pd.DataFrame)
    speeders:               dict[str, pd.DataFrame] = field(default_factory=dict)
    oe_flags:               pd.DataFrame = field(default_factory=pd.DataFrame)
    summary:                dict[str, Any] = field(default_factory=dict)


class QCEngine:
    """
    Runs all configured QC checks against a filtered DataFrame.

    Parameters
    ----------
    cfg:
        The full merged config dict.
    """

    def __init__(self, cfg: dict) -> None:
        self._cfg  = cfg
        self._cols = cfg["columns"]

    # ── Public entry-point ─────────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> QCResult:
        """
        Execute all enabled QC checks and return a ``QCResult``.

        Parameters
        ----------
        df:
            The already-filtered (e.g. GC=1) DataFrame.
        """
        result = QCResult()

        dup_cfg = self._cfg.get("duplicates", {})
        if dup_cfg.get("check_ip", True):
            result.ip_duplicates = self._ip_duplicates(df)

        if dup_cfg.get("check_identifier", True):
            result.identifier_duplicates = self._identifier_duplicates(df)

        for spec in self._cfg.get("speeder_thresholds", []):
            label     = spec["label"]
            threshold = float(spec["threshold_minutes"])
            result.speeders[label] = self._speeders(df, threshold)

        oe_cfg = self._cfg.get("oe_scrubbing", {})
        if oe_cfg.get("enabled", True):
            result.oe_flags = self._scrub_oe(df, oe_cfg)

        result.summary = self._build_summary(df, result)
        return result

    # ── Duplicate checks ───────────────────────────────────────────────

    def _ip_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return rows where IPAddress appears more than once."""
        rid_col = self._cols["response_id"]
        ip_col  = self._cols["ip"]

        if ip_col not in df.columns:
            logger.warning("IP column '%s' not found — check skipped.", ip_col)
            return pd.DataFrame()

        counts   = df[ip_col].value_counts()
        dup_ips  = counts[counts > 1].index
        if len(dup_ips) == 0:
            return pd.DataFrame()

        report = (
            df[df[ip_col].isin(dup_ips)][[rid_col, ip_col]]
            .copy()
            .rename(columns={rid_col: "ResponseId", ip_col: "Duplicate_IP"})
            .sort_values(["Duplicate_IP", "ResponseId"])
            .reset_index(drop=True)
        )
        logger.info("IP duplicates: %d rows across %d IPs.", len(report), len(dup_ips))
        return report

    def _identifier_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return rows where the identifier column appears more than once."""
        rid_col = self._cols["response_id"]
        id_col  = self._cols["identifier"]

        if id_col not in df.columns:
            logger.warning(
                "Identifier column '%s' not found — check skipped.", id_col
            )
            return pd.DataFrame()

        counts  = df[id_col].value_counts()
        dup_ids = counts[counts > 1].index
        if len(dup_ids) == 0:
            return pd.DataFrame()

        report = (
            df[df[id_col].isin(dup_ids)][[rid_col, id_col]]
            .copy()
            .rename(columns={rid_col: "ResponseId", id_col: "Duplicate_Identifier"})
            .sort_values(["Duplicate_Identifier", "ResponseId"])
            .reset_index(drop=True)
        )
        logger.info(
            "Identifier duplicates: %d rows across %d identifiers.",
            len(report), len(dup_ids),
        )
        return report

    # ── Speeder check ──────────────────────────────────────────────────

    def _speeders(self, df: pd.DataFrame, threshold_min: float) -> pd.DataFrame:
        """Return rows where duration ≤ threshold (in minutes)."""
        rid_col = self._cols["response_id"]
        dur_col = self._cols["duration"]

        if dur_col not in df.columns:
            logger.warning(
                "Duration column '%s' not found — speeder check skipped.", dur_col
            )
            return pd.DataFrame()

        tmp = df[[rid_col, dur_col]].copy()
        tmp[dur_col] = pd.to_numeric(tmp[dur_col], errors="coerce") / 60.0
        speeders = (
            tmp[tmp[dur_col] <= threshold_min]
            .copy()
            .rename(columns={rid_col: "ResponseId", dur_col: "Time_Minutes"})
            .assign(Time_Minutes=lambda x: x["Time_Minutes"].round(2))
            .sort_values("Time_Minutes")
            .reset_index(drop=True)
        )
        logger.info(
            "Speeders ≤ %.1f min: %d rows.", threshold_min, len(speeders)
        )
        return speeders

    # ── OE text scrubbing ──────────────────────────────────────────────

    def _scrub_oe(self, df: pd.DataFrame, oe_cfg: dict) -> pd.DataFrame:
        """
        Scan open-ended text columns and return a flag report.

        Each flagged response produces one row with columns:
          ResponseId | Column | Response | Flags
        """
        mode       = oe_cfg.get("mode", "auto")
        min_len    = int(oe_cfg.get("min_length", 3))
        max_len    = int(oe_cfg.get("max_length", 5000))
        profanity  = bool(oe_cfg.get("profanity_filter", True))
        gibberish  = bool(oe_cfg.get("gibberish_check", True))
        gibber_thr = float(oe_cfg.get("gibberish_unique_char_ratio", 0.85))

        # Determine which columns to check
        if mode == "auto":
            oe_cols = [c for c in df.columns if str(c).upper().endswith("_TEXT")]
        else:
            oe_cols = [c for c in oe_cfg.get("columns", []) if c in df.columns]

        if not oe_cols:
            logger.info("No OE columns found to scrub.")
            return pd.DataFrame()

        logger.info("Scrubbing %d OE column(s): %s", len(oe_cols), oe_cols)

        rid_col = self._cols["response_id"]
        rows: list[dict] = []

        for col in oe_cols:
            for _, record in df[[rid_col, col]].iterrows():
                resp = record[col]
                if pd.isna(resp) or str(resp).strip() == "":
                    continue

                text  = str(resp).strip()
                flags = self._classify_oe(
                    text,
                    min_len=min_len,
                    max_len=max_len,
                    check_profanity=profanity,
                    check_gibberish=gibberish,
                    gibber_thr=gibber_thr,
                )
                if flags:
                    rows.append({
                        "ResponseId": record[rid_col],
                        "Column":     col,
                        "Response":   text[:200],   # truncate for readability
                        "Flags":      " | ".join(flags),
                    })

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows).reset_index(drop=True)

    # ── OE classifiers ─────────────────────────────────────────────────

    @staticmethod
    def _classify_oe(
        text: str,
        *,
        min_len: int,
        max_len: int,
        check_profanity: bool,
        check_gibberish: bool,
        gibber_thr: float,
    ) -> list[str]:
        """
        Return a list of flag strings for *text*.  Empty list = clean.
        """
        flags: list[str] = []

        if len(text) < min_len:
            flags.append(f"too_short (<{min_len} chars)")

        if len(text) > max_len:
            flags.append(f"too_long (>{max_len} chars)")

        if check_profanity:
            for pat in _PROFANITY_PATTERNS:
                if pat.search(text):
                    flags.append("profanity")
                    break

        if check_gibberish and QCEngine._is_gibberish(text, gibber_thr):
            flags.append("gibberish")

        return flags

    @staticmethod
    def _is_gibberish(text: str, unique_ratio_threshold: float) -> bool:
        """
        Simple gibberish heuristic:

        1. Strip spaces and punctuation.
        2. If the ratio of unique characters to total characters is very
           high (e.g. > 0.85) the text is likely keyboard-mash.
        3. Additionally flag if the text contains no vowels (> 4 chars).
        """
        cleaned = re.sub(r"[\s" + re.escape(string.punctuation) + r"]", "", text)
        if len(cleaned) < 4:
            return False

        unique_ratio = len(set(cleaned.lower())) / len(cleaned)
        if unique_ratio > unique_ratio_threshold:
            return True

        vowels = set("aeiouAEIOU")
        if len(cleaned) > 4 and not any(c in vowels for c in cleaned):
            return True

        return False

    # ── Summary ────────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(df: pd.DataFrame, result: QCResult) -> dict[str, Any]:
        """Build a human-readable summary dict."""
        speeder_counts = {
            label: len(rpt) for label, rpt in result.speeders.items()
        }
        return {
            "total_gc_filtered_rows": len(df),
            "ip_duplicate_rows":          len(result.ip_duplicates),
            "identifier_duplicate_rows":  len(result.identifier_duplicates),
            "speeder_rows":               speeder_counts,
            "oe_flagged_rows":            len(result.oe_flags),
        }
