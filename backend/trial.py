"""
trial.py — first-launch-based trial management.

The first time the app runs, it writes the launch date to ~/.pcc/config.json.
This date never changes after that, so re-installing does not extend the trial.
The BUILD_DATE is still baked in at compile time as a fallback identifier.

Trial logic:
  - Full access for TRIAL_DAYS days from first launch
  - After expiry: freemium mode — deterministic features only, LLM disabled
"""

import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Literal

# ── Build-time constant (replaced by build script) ────────────────────────────
BUILD_DATE = "2026-08-04"

TRIAL_DAYS = 100

SECRET = b"pcc-trial-v1-fd2025"

# ── Feature tiers ─────────────────────────────────────────────────────────────
FREE_FEATURES = {
    "compliance", "stats", "coi", "data",
    "config", "settings", "about", "camera",
}

PREMIUM_FEATURES = {
    "screening", "reviews", "decisions", "program", "emails",
}


def _config_path() -> Path:
    return Path.home() / ".pcc" / "config.json"


def _get_or_set_first_launch() -> date:
    """
    Return the first-launch date, creating it if this is the first run.
    Stored in ~/.pcc/config.json under 'first_launch'.
    """
    # Development mode — no expiry
    is_dev = BUILD_DATE.strip() == "BUILD_DATE_PLACEHOLDER"
    if is_dev:
        return date.today()

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config
    config = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except Exception:
            config = {}

    # Already have a first_launch date
    if "first_launch" in config:
        try:
            return datetime.strptime(config["first_launch"], "%Y-%m-%d").date()
        except Exception:
            pass

    # First run — record today
    today_str = date.today().isoformat()
    config["first_launch"] = today_str
    try:
        path.write_text(json.dumps(config, indent=2))
    except Exception:
        pass
    return date.today()


def get_trial_status() -> dict:
    """Return the current trial status."""
    is_dev = BUILD_DATE.strip() == "BUILD_DATE_PLACEHOLDER"
    first_launch = _get_or_set_first_launch()
    today = date.today()
    days_elapsed   = (today - first_launch).days
    days_remaining = max(0, TRIAL_DAYS - days_elapsed)

    if is_dev:
        mode = "development"
    elif days_elapsed <= TRIAL_DAYS:
        mode = "trial"
    else:
        mode = "freemium"

    return {
        "mode":             mode,
        "build_date":       BUILD_DATE.strip(),
        "first_launch":     str(first_launch),
        "days_elapsed":     days_elapsed,
        "days_remaining":   days_remaining,
        "trial_days":       TRIAL_DAYS,
        "is_dev":           is_dev,
        "free_features":    sorted(FREE_FEATURES),
        "premium_features": sorted(PREMIUM_FEATURES),
        "full_access":      mode in ("development", "trial"),
    }


def is_feature_allowed(feature_id: str) -> bool:
    status = get_trial_status()
    if status["full_access"]:
        return True
    return feature_id in FREE_FEATURES


def require_full_access(feature_id: str):
    from fastapi import HTTPException
    if not is_feature_allowed(feature_id):
        raise HTTPException(
            status_code=402,
            detail={
                "error":   "trial_expired",
                "feature": feature_id,
                "message": (
                    f"Your 30-day trial has expired. "
                    f"This feature requires a full license. "
                    f"Contact florenc1991@gmail.com for licensing."
                ),
            }
        )
