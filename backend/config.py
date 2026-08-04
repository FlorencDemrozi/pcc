"""
config.py — local configuration store.
Saves to ~/.pcc/config.json on the user's machine.
"""

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".pcc"
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULTS = {
    "anthropic_api_key": "",
    "llm": {
        "provider": "claude",
        "claude_key": "",
        "openai_key": "",
        "gemini_key": "",
        "groq_key": "",
        "ollama_url": "http://localhost:11434",
        "models": {},
    },
    "conference": {
        "name": "",
        "acronym": "",
        "edition": "",
        "year": "",
        "dates": "",
        "venue": "",
        "city": "",
        "country": "",
        "website": "",
        "submissionSystem": "EasyChair",
        "maxPages": 6,
        "doubleBlind": True,
        "template": "Two-column conference template",
        "scope": "",
        "keywords": [],
        "deadlines": [],
        "tracks": [],
        "organizers": [],
        "sponsors": [],
        "indexing": [],
        "notes": "",
        "copyrightNotices": [],
        "validationStamp": "",
        "institutionSynonyms": {},
    }
}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    _ensure_dir()
    if not CONFIG_FILE.exists():
        return json.loads(json.dumps(_DEFAULTS))
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        # Deep merge with defaults to ensure all keys exist
        merged = json.loads(json.dumps(_DEFAULTS))
        merged.update(data)
        if "conference" in data:
            merged["conference"].update(data["conference"])
        return merged
    except Exception:
        return json.loads(json.dumps(_DEFAULTS))


def save(data: dict) -> bool:
    _ensure_dir()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def get_api_key() -> str:
    c = load()
    # Support both old key location and new llm.claude_key
    return c.get("llm", {}).get("claude_key", "") or c.get("anthropic_api_key", "")


def set_api_key(key: str) -> bool:
    cfg = load()
    cfg["anthropic_api_key"] = key
    if "llm" not in cfg:
        cfg["llm"] = _DEFAULTS["llm"].copy()
    cfg["llm"]["claude_key"] = key
    return save(cfg)


def get_llm_config() -> dict:
    return load().get("llm", _DEFAULTS["llm"].copy())


def set_llm_config(llm: dict) -> bool:
    cfg = load()
    cfg["llm"] = llm
    # Keep legacy key in sync
    cfg["anthropic_api_key"] = llm.get("claude_key", "")
    return save(cfg)


def get_conference() -> dict:
    return load().get("conference", _DEFAULTS["conference"])


def set_conference(conf: dict) -> bool:
    cfg = load()
    cfg["conference"] = conf
    return save(cfg)
