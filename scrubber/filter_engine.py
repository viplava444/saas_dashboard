"""
scrubber/filter_engine.py
─────────────────────────
Config-driven row filter.

Evaluates the ``gc_filter`` block from the config and returns only the
rows that pass.  Supports the following operators:

  =         equality
  !=        inequality
  >  >=  <  <= numeric comparisons
  in        value is in a list
  not_in    value is not in a list

All comparisons are performed after coercing the column to numeric where
possible, so "1" == 1 works correctly.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Operators that require the right-hand side to be a list
_LIST_OPS = {"in", "not_in"}

# Supported operators mapped to their pandas / Python equivalents
_NUMERIC_OPS = {">", ">=", "<", "<="}


class FilterEngine:
    """
    Applies the configured condition filter to a DataFrame.

    Parameters
    ----------
    cfg:
        The full merged config dict.
    """

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter *df* according to the ``gc_filter`` config block.

        Returns
        -------
        pd.DataFrame
            A copy containing only the rows that satisfy the condition.
            If the column is missing the original DataFrame is returned
            unchanged (with a warning).
        """
        fc     = self._cfg["gc_filter"]
        col    = fc.get("column") or self._cfg["columns"]["gc"]
        op     = str(fc["operator"]).strip().lower()
        value  = fc["value"]

        if col not in df.columns:
            logger.warning(
                "GC filter column '%s' not found in DataFrame — filter skipped.", col
            )
            return df

        series = df[col].copy()

        # Coerce to numeric for any operator that needs it
        if op not in _LIST_OPS:
            series = pd.to_numeric(series, errors="coerce")
            if op in _NUMERIC_OPS:
                value = float(value)
            else:
                # equality / inequality: try numeric coercion of value too
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass

        mask = self._build_mask(series, op, value)

        total   = len(df)
        passing = int(mask.sum())
        logger.info(
            "GC filter '%s %s %s': %d / %d rows pass.",
            col, op, value, passing, total,
        )
        return df[mask].copy()

    # ── Private ────────────────────────────────────────────────────────

    @staticmethod
    def _build_mask(series: pd.Series, op: str, value: Any) -> pd.Series:
        """Build a boolean mask for *series* given *op* and *value*."""
        if op == "=":
            return series == value
        if op == "!=":
            return series != value
        if op == ">":
            return series > value
        if op == ">=":
            return series >= value
        if op == "<":
            return series < value
        if op == "<=":
            return series <= value
        if op == "in":
            if not isinstance(value, list):
                raise ValueError(
                    f"Operator 'in' requires a list value, got {type(value).__name__}."
                )
            return series.isin(value)
        if op == "not_in":
            if not isinstance(value, list):
                raise ValueError(
                    f"Operator 'not_in' requires a list value, got {type(value).__name__}."
                )
            return ~series.isin(value)

        raise ValueError(
            f"Unknown filter operator '{op}'. "
            "Supported: =  !=  >  >=  <  <=  in  not_in"
        )
