"""
scrubber/learning_store.py
──────────────────────────
Human-in-the-loop feedback persistence.

Stores reviewer decisions for OE responses in a JSON file.
When enough "invalid" labels accumulate for a pattern, it can be
promoted to an automatic reject rule.

Design constraints (per spec):
  • Controlled  — rules are only promoted when threshold is met
  • Transparent — every decision is stored with timestamp + reviewer
  • Reversible  — rules can be demoted / deleted explicitly

Storage schema (JSON)
─────────────────────
{
  "feedback": [
    {
      "response_id": "R_abc123",
      "column":      "Q5_TEXT",
      "text":        "asdfghjkl",
      "label":       "invalid",      // valid | invalid | borderline
      "reviewer":    "admin",
      "timestamp":   "2024-01-15T10:30:00"
    },
    ...
  ],
  "auto_rules": [
    {
      "pattern":    "asdfghjkl",
      "rule_type":  "exact",          // exact | contains | regex
      "promoted_at":"2024-01-15T10:30:00",
      "source":     "feedback_auto"
    },
    ...
  ]
}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Label = Literal["valid", "invalid", "borderline"]


class LearningStore:
    """
    Persistent storage for OE review feedback and auto-promoted rules.

    Parameters
    ----------
    cfg:
        The full merged config dict.
    """

    def __init__(self, cfg: dict) -> None:
        learn_cfg       = cfg.get("learning", {})
        self._enabled   = bool(learn_cfg.get("enabled", True))
        self._threshold = int(learn_cfg.get("auto_promote_threshold", 5))
        self._path      = Path(learn_cfg.get("storage_path", "learning/feedback_store.json"))
        self._data: dict = {"feedback": [], "auto_rules": []}

        if self._enabled:
            self._load()

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record_feedback(
        self,
        response_id: str,
        column: str,
        text: str,
        label: Label,
        reviewer: str = "admin",
    ) -> None:
        """
        Persist a reviewer's decision for one OE response.

        After saving, checks whether any pattern now crosses the
        auto-promote threshold and promotes it if so.
        """
        if not self._enabled:
            return

        entry = {
            "response_id": response_id,
            "column":      column,
            "text":        text,
            "label":       label,
            "reviewer":    reviewer,
            "timestamp":   _now(),
        }
        self._data["feedback"].append(entry)
        self._save()
        logger.debug("Feedback recorded: %s → %s", response_id, label)

        if label == "invalid":
            self._check_promote(text)

    def get_auto_rules(self) -> list[dict]:
        """Return the current list of auto-promoted reject rules."""
        return list(self._data.get("auto_rules", []))

    def demote_rule(self, pattern: str) -> bool:
        """
        Remove an auto-promoted rule by its pattern string.

        Returns True if the rule was found and removed, False otherwise.
        """
        before = len(self._data["auto_rules"])
        self._data["auto_rules"] = [
            r for r in self._data["auto_rules"] if r["pattern"] != pattern
        ]
        removed = len(self._data["auto_rules"]) < before
        if removed:
            self._save()
            logger.info("Auto-rule demoted: '%s'", pattern)
        return removed

    def export_rules(self, path: str | Path) -> None:
        """Export auto-promoted rules to a JSON file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            json.dump(self._data["auto_rules"], fh, indent=2)
        logger.info("Auto-rules exported to %s", out)

    def import_rules(self, path: str | Path) -> int:
        """
        Import rules from a JSON file, skipping duplicates.

        Returns the number of new rules added.
        """
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"Import file not found: {src}")

        with src.open("r", encoding="utf-8") as fh:
            incoming: list[dict] = json.load(fh)

        existing_patterns = {r["pattern"] for r in self._data["auto_rules"]}
        added = 0
        for rule in incoming:
            if rule.get("pattern") not in existing_patterns:
                self._data["auto_rules"].append(rule)
                added += 1

        if added:
            self._save()
        logger.info("Imported %d new rule(s) from %s", added, src)
        return added

    def matches_auto_rule(self, text: str) -> bool:
        """
        Return True if *text* matches any auto-promoted reject rule.
        Supports rule_type: exact | contains | regex.
        """
        import re as _re

        for rule in self._data.get("auto_rules", []):
            pattern   = rule.get("pattern", "")
            rule_type = rule.get("rule_type", "contains")
            try:
                if rule_type == "exact" and text.strip() == pattern:
                    return True
                if rule_type == "contains" and pattern.lower() in text.lower():
                    return True
                if rule_type == "regex" and _re.search(pattern, text, _re.IGNORECASE):
                    return True
            except Exception:
                pass
        return False

    # ── Private ────────────────────────────────────────────────────────

    def _check_promote(self, text: str) -> None:
        """Promote *text* to an auto-rule if it has ≥ threshold invalid labels."""
        invalid_count = sum(
            1
            for fb in self._data["feedback"]
            if fb["label"] == "invalid" and fb["text"].strip() == text.strip()
        )
        existing = {r["pattern"] for r in self._data["auto_rules"]}
        if invalid_count >= self._threshold and text.strip() not in existing:
            rule = {
                "pattern":     text.strip(),
                "rule_type":   "exact",
                "promoted_at": _now(),
                "source":      "feedback_auto",
            }
            self._data["auto_rules"].append(rule)
            self._save()
            logger.info(
                "Pattern auto-promoted to reject rule (%d labels): '%s'",
                invalid_count, text.strip()[:60],
            )

    def _load(self) -> None:
        if not self._path.exists():
            logger.debug("No feedback store found at %s — starting fresh.", self._path)
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            self._data = {
                "feedback":   loaded.get("feedback", []),
                "auto_rules": loaded.get("auto_rules", []),
            }
            logger.debug(
                "Loaded %d feedback entries, %d auto-rules from %s.",
                len(self._data["feedback"]),
                len(self._data["auto_rules"]),
                self._path,
            )
        except json.JSONDecodeError as exc:
            logger.error("Corrupt feedback store (%s) — starting fresh: %s", self._path, exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
