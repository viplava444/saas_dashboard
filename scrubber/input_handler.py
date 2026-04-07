"""
scrubber/input_handler.py
─────────────────────────
Multi-format survey file loader.

Supports:
  • CSV  (.csv)
  • TSV  (.tsv)
  • Excel (.xlsx, .xls)

Handles:
  • Automatic file-type detection from extension
  • Encoding fallback chain (UTF-8 → UTF-16 → latin-1)
  • Optional delimiter override for CSV/TSV
  • Excel sheet selection (name or 0-based index)
  • Qualtrics survey files: skips the label row (row index 1) and
    the ImportId row (row index 2) that Qualtrics exports by default.
  • Basic header validation
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import IO

import pandas as pd

logger = logging.getLogger(__name__)

# Encoding fallback order
_ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "latin-1"]

# File-type → (is_excel, default_delimiter)
_EXT_MAP: dict[str, tuple[bool, str | None]] = {
    ".csv":  (False, ","),
    ".tsv":  (False, "\t"),
    ".xlsx": (True,  None),
    ".xls":  (True,  None),
}


class InputHandler:
    """
    Loads a survey data file into a ``pandas.DataFrame``.

    Parameters
    ----------
    filepath:
        Path to the input file.
    delimiter:
        Override the auto-detected delimiter (CSV/TSV only).
    sheet:
        Sheet name or 0-based index for Excel files (default: 0).
    skip_qualtrics_rows:
        When True (default), drops the Qualtrics label and ImportId
        rows that appear at rows 1–2 of exported survey CSVs.
    """

    def __init__(
        self,
        filepath: str | Path,
        delimiter: str | None = None,
        sheet: str | int = 0,
        skip_qualtrics_rows: bool = True,
    ) -> None:
        self.filepath = Path(filepath)
        self.delimiter = delimiter
        self.sheet = sheet
        self.skip_qualtrics_rows = skip_qualtrics_rows

    # ── Public ─────────────────────────────────────────────────────────

    def load(self) -> pd.DataFrame:
        """
        Read the file and return a standardised DataFrame.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If the file extension is not supported.
        RuntimeError
            If the file cannot be read with any known encoding.
        """
        if not self.filepath.exists():
            raise FileNotFoundError(f"Input file not found: {self.filepath}")

        ext = self.filepath.suffix.lower()
        if ext not in _EXT_MAP:
            raise ValueError(
                f"Unsupported file type '{ext}'. "
                f"Supported: {', '.join(_EXT_MAP)}"
            )

        is_excel, default_delim = _EXT_MAP[ext]
        df = self._load_excel() if is_excel else self._load_flat(default_delim)

        logger.info(
            "Loaded '%s': %d rows × %d columns.",
            self.filepath.name, len(df), len(df.columns),
        )

        if self.skip_qualtrics_rows:
            df = self._drop_qualtrics_meta_rows(df)

        return df

    # ── Private ────────────────────────────────────────────────────────

    def _load_flat(self, default_delim: str | None) -> pd.DataFrame:
        """Load CSV or TSV with encoding fallback."""
        delim = self.delimiter or default_delim or ","
        last_exc: Exception | None = None

        for enc in _ENCODINGS:
            try:
                df = pd.read_csv(
                    self.filepath,
                    delimiter=delim,
                    encoding=enc,
                    low_memory=False,
                    dtype=str,          # read everything as str; cast later
                )
                logger.debug("Read '%s' with encoding '%s'.", self.filepath.name, enc)
                return df
            except (UnicodeDecodeError, UnicodeError) as exc:
                last_exc = exc
                logger.debug("Encoding '%s' failed, trying next.", enc)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to parse '{self.filepath.name}': {exc}"
                ) from exc

        raise RuntimeError(
            f"Could not read '{self.filepath.name}' with any known encoding. "
            f"Last error: {last_exc}"
        )

    def _load_excel(self) -> pd.DataFrame:
        """Load Excel (.xlsx / .xls)."""
        try:
            df = pd.read_excel(
                self.filepath,
                sheet_name=self.sheet,
                dtype=str,
                engine="openpyxl" if self.filepath.suffix.lower() == ".xlsx" else None,
            )
            logger.debug(
                "Read Excel sheet '%s' from '%s'.",
                self.sheet, self.filepath.name,
            )
            return df
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read Excel file '{self.filepath.name}': {exc}"
            ) from exc

    @staticmethod
    def _drop_qualtrics_meta_rows(df: pd.DataFrame) -> pd.DataFrame:
        """
        Qualtrics exports two extra rows below the header:
          Row 1 (index 0 after read): human-readable question labels
          Row 2 (index 1 after read): ImportId values like {"ImportId":"QID1"}

        Drop them if the second column of row 0 looks like a label (non-numeric
        string) and row 1 starts with ``{``, which is characteristic of
        Qualtrics ImportId JSON.
        """
        if len(df) < 2:
            return df

        first_data_val = str(df.iloc[0, 1]) if len(df.columns) > 1 else ""
        second_data_val = str(df.iloc[1, 0])

        is_label_row  = not first_data_val.lstrip("+-").replace(".", "", 1).isdigit()
        is_import_row = second_data_val.strip().startswith("{")

        if is_label_row and is_import_row:
            df = df.iloc[2:].reset_index(drop=True)
            logger.debug("Dropped 2 Qualtrics meta rows.")
        elif is_label_row:
            df = df.iloc[1:].reset_index(drop=True)
            logger.debug("Dropped 1 Qualtrics label row.")

        return df


def validate_required_columns(df: pd.DataFrame, required: list[str]) -> list[str]:
    """
    Return a list of column names from *required* that are absent in *df*.
    An empty list means all required columns are present.
    """
    return [col for col in required if col not in df.columns]
