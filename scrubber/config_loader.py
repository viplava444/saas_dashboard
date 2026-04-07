"""
scrubber/config_loader.py
─────────────────────────
Loads the default YAML config and deep-merges any user-supplied override
file on top of it.  The result is a plain dict accessible throughout the
pipeline.

Design principle: "Convention by default, configuration by override."
Only keys present in the override file are changed; everything else
falls back to the packaged defaults.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Path to the bundled default config (lives next to this package)
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "qc_config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge *override* into *base*.

    - Dicts are merged key-by-key (nested overrides are supported).
    - Any other type: the override value replaces the base value outright.
    - *base* is never mutated; a deep copy is returned.
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def load_config(user_config_path: str | Path | None = None) -> dict[str, Any]:
    """
    Load and return the merged configuration dict.

    Parameters
    ----------
    user_config_path:
        Optional path to a user YAML override file.  Only the keys you
        want to change need to be present.  Pass ``None`` (default) to
        use the packaged defaults unchanged.

    Returns
    -------
    dict
        Fully merged configuration ready for use by the pipeline.
    """
    # ── Load defaults ──────────────────────────────────────────────────
    if not _DEFAULT_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Default config not found at {_DEFAULT_CONFIG_PATH}. "
            "Ensure config/qc_config.yaml is present."
        )

    with _DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        defaults: dict = yaml.safe_load(fh) or {}

    if user_config_path is None:
        logger.debug("No user config supplied — using defaults.")
        return defaults

    # ── Load user overrides ────────────────────────────────────────────
    user_path = Path(user_config_path)
    if not user_path.exists():
        raise FileNotFoundError(f"User config file not found: {user_path}")

    with user_path.open("r", encoding="utf-8") as fh:
        user_overrides: dict = yaml.safe_load(fh) or {}

    merged = _deep_merge(defaults, user_overrides)
    logger.info("User config '%s' merged with defaults.", user_path)
    return merged


def get_column(cfg: dict, key: str) -> str:
    """
    Convenience: resolve a logical column name from ``cfg['columns']``.

    Example
    -------
    >>> col = get_column(cfg, 'response_id')   # → 'ResponseId'
    """
    return cfg["columns"][key]
