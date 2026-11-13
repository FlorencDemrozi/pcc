"""
config.py — local configuration store.
Saves to ~/.pcc/config.json on the user's machine.

Writes are atomic (temp file + os.replace) and serialised with a lock, so a
crash or concurrent request can never leave a half-written config behind.
A config file that cannot be parsed is backed up, never silently overwritten.
"""

import copy
import json
import os
import tempfile
import threading
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".pcc"
CONFIG_FILE = CONFIG_DIR / "config.json"

# openalex_key: optional, free key for reference verification (not an LLM)
KEY_FIELDS = ("claude_key", "openai_key", "gemini_key", "groq_key", "openalex_key")

_LOCK = threading.RLock()

_DEFAULTS = {
    "anthropic_api_key": "",
    "llm": {
        "provider": "claude",
        "claude_key": "",
        "openai_key": "",
        "gemini_key": "",
        "groq_key": "",
        "openalex_key": "",
        "ollama_url": "http://localhost:11434",
        "models": {},
        "module_tiers": {},
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


def _defaults() -> dict:
    return copy.deepcopy(_DEFAULTS)


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def _backup_corrupt():
    """Move an unreadable config aside so the next save cannot destroy it."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.corrupt-{stamp}")
    try:
        os.replace(CONFIG_FILE, backup)
    except OSError:
        pass


def load() -> dict:
    with _LOCK:
        _ensure_dir()
        if not CONFIG_FILE.exists():
            return _defaults()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("config root is not an object")
        except Exception:
            _backup_corrupt()
            return _defaults()
        # Deep merge with defaults to ensure all keys exist
        merged = _defaults()
        merged.update(data)
        for section in ("llm", "conference"):
            if isinstance(data.get(section), dict):
                merged[section] = {**_DEFAULTS[section], **data[section]}
            else:
                merged[section] = copy.deepcopy(_DEFAULTS[section])
        return merged


def save(data: dict) -> bool:
    with _LOCK:
        _ensure_dir()
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(CONFIG_DIR))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, CONFIG_FILE)
            tmp_path = None
            return True
        except Exception:
            return False
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def get_api_key() -> str:
    c = load()
    # Support both old key location and new llm.claude_key
    return c.get("llm", {}).get("claude_key", "") or c.get("anthropic_api_key", "")


def set_api_key(key: str) -> bool:
    with _LOCK:
        cfg = load()
        cfg["anthropic_api_key"] = key
        cfg.setdefault("llm", copy.deepcopy(_DEFAULTS["llm"]))
        cfg["llm"]["claude_key"] = key
        return save(cfg)


def get_llm_config() -> dict:
    return load().get("llm", copy.deepcopy(_DEFAULTS["llm"]))


def _merge_llm(current: dict, update: dict) -> dict:
    """
    Merge an LLM settings update into the stored block.
    - Key fields: empty / missing value keeps the stored key; keys listed in
      update["clear_keys"] are cleared explicitly.
    - models / module_tiers dicts are merged (a value of None/"" removes an entry).
    - Other scalar fields (provider, ollama_url) are replaced when present.
    """
    merged = {**_DEFAULTS["llm"], **(current or {})}
    update = update or {}

    for k in KEY_FIELDS:
        v = update.get(k)
        if isinstance(v, str) and v.strip():
            merged[k] = v.strip()

    clear = update.get("clear_keys") or []
    if isinstance(clear, str):
        clear = [clear]
    for k in clear:
        name = k if k.endswith("_key") else f"{k}_key"
        if name in KEY_FIELDS:
            merged[name] = ""

    for field in ("provider", "ollama_url"):
        v = update.get(field)
        if isinstance(v, str) and v.strip():
            merged[field] = v.strip()

    for field in ("models", "module_tiers"):
        v = update.get(field)
        if isinstance(v, dict):
            d = dict(merged.get(field) or {})
            for mk, mv in v.items():
                if mv in (None, ""):
                    d.pop(mk, None)
                elif field == "module_tiers" and mv not in ("fast", "full"):
                    continue
                else:
                    d[str(mk)] = mv
            merged[field] = d
    return merged


def set_llm_config(llm: dict) -> bool:
    with _LOCK:
        cfg = load()
        cfg["llm"] = _merge_llm(cfg.get("llm", {}), llm)
        _sync_legacy(cfg, llm)
        return save(cfg)


def _sync_legacy(cfg: dict, update: dict):
    """Keep the legacy top-level Claude key in sync without ever wiping it by accident."""
    claude = cfg["llm"].get("claude_key", "")
    if claude:
        cfg["anthropic_api_key"] = claude
    else:
        clear = (update or {}).get("clear_keys") or []
        if isinstance(clear, str):
            clear = [clear]
        if "claude_key" in clear or "claude" in clear:
            cfg["anthropic_api_key"] = ""


def update_config(body: dict) -> bool:
    """
    Update top-level config sections from a client payload.
    The 'llm' block is routed through _merge_llm (so keys can't be wiped or
    replaced wholesale) and the legacy 'anthropic_api_key' is never written here.
    Redaction-only fields (*_set / *_masked) are ignored.
    """
    if not isinstance(body, dict):
        return False
    with _LOCK:
        cfg = load()
        for k, v in body.items():
            if k == "anthropic_api_key" or k.endswith("_set") or k.endswith("_masked"):
                continue
            if k == "llm":
                if isinstance(v, dict):
                    cfg["llm"] = _merge_llm(cfg.get("llm", {}), v)
                    _sync_legacy(cfg, v)
                continue
            cfg[k] = v
        return save(cfg)


def redacted(cfg: dict) -> dict:
    """Return a copy of the config with every API key removed (masked status only)."""
    out = copy.deepcopy(cfg)
    legacy = out.pop("anthropic_api_key", "")
    out["anthropic_api_key_set"] = bool(legacy)
    llm = out.get("llm")
    if isinstance(llm, dict):
        for k in KEY_FIELDS:
            val = llm.pop(k, "") or ""
            llm[f"{k}_set"] = bool(val)
            llm[f"{k}_masked"] = mask(val)
    return out


def mask(k: str) -> str:
    k = k or ""
    return ("*" * (len(k) - 4) + k[-4:]) if len(k) > 4 else "*" * len(k)


def get_conference() -> dict:
    return load().get("conference", copy.deepcopy(_DEFAULTS["conference"]))


def set_conference(conf: dict) -> bool:
    with _LOCK:
        cfg = load()
        cfg["conference"] = conf
        return save(cfg)
