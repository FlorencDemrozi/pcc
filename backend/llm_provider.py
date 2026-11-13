"""
llm_provider.py — unified LLM call abstraction.
Routes to Claude, OpenAI, Gemini, Groq, or Ollama based on config.
Supports model tiers: 'full' (best model) and 'fast' (cheaper/faster model).
"""

import asyncio
import base64
import io
import re
from typing import Optional
import httpx
import config as cfg


# ── Provider definitions ──────────────────────────────────────────────────────
# Built-in default model IDs (checked November 2026). Providers retire model IDs
# regularly; users can override any of these in Settings via the `models` dict
# (keys like "claude_full_model", "openai_fast_model", "gemini_full_model", ...).

PROVIDERS = {
    "claude": {
        "name": "Claude (Anthropic)", "pdf": "native",
        "models": {
            "full": "claude-sonnet-5-5",
            "fast": "claude-haiku-5-5",
        }
    },
    "openai": {
        # Native PDF input via Chat Completions "file" content parts
        # (falls back to extracted text if the request is rejected).
        "name": "ChatGPT (OpenAI)", "pdf": "native",
        "models": {
            "full": "gpt-6-astra",
            "fast": "gpt-6-luna",
        }
    },
    "gemini": {
        # Stable models; the frontier "gemini-4-carbon" can be set as an override in Settings.
        "name": "Gemini (Google)", "pdf": "native",
        "models": {
            "full": "gemini-3.8-flash",
            "fast": "gemini-3.5-flash-lite",
        }
    },
    "groq": {
        "name": "Groq", "pdf": "text",
        "models": {
            "full": "openai/gpt-oss-120b",
            "fast": "openai/gpt-oss-20b",
        }
    },
    "ollama": {
        "name": "Ollama (local)", "pdf": "text",
        "models": {
            "full": "llama3",
            "fast": "llama3",
        }
    },
}

# Tasks and their recommended tier
# 'fast' = cheaper model OK, 'full' = needs best model
TASK_TIERS = {
    "screening":    "full",   # AI paper quality — needs full model
    "decisions":    "full",   # Accept/reject decisions — needs full model
    "review_quality": "fast", # Review quality assessment — fast model sufficient
    "blind":        "fast",   # Blind compliance — fast model sufficient
    "coi_expand":   "fast",   # Affiliation synonym expansion — fast OK
    "program":      "full",   # Program building — needs full model
    "email":        "fast",   # Email drafting — fast OK
    "cfp_extract":  "fast",   # CFP extraction — fast OK
    "file_parse":   "fast",   # Unknown-format file parsing fallback
    "default":      "full",
}

# Task names sent by the frontend that map onto a Settings module id.
_TASK_ALIASES = {
    "reviews": "review_quality",
    "emails":  "email",
    "config":  "cfp_extract",
}

_DEFAULT_LLM = {
    "provider": "claude",
    "claude_key": "",
    "openai_key": "",
    "gemini_key": "",
    "groq_key": "",
    "ollama_url": "http://localhost:11434",
    "models": {},
    "module_tiers": {},  # per-module override: { module_id: "full"|"fast" }
}


def get_provider_config() -> dict:
    c = cfg.load()
    return c.get("llm") or dict(_DEFAULT_LLM)


def get_active_provider() -> str:
    return get_provider_config().get("provider", "claude")


def _model_for(provider: str, tier: str = "full", pc: Optional[dict] = None) -> str:
    """Get the model name for a provider and tier."""
    pc = pc if pc is not None else get_provider_config()
    # Check for user override first
    override_key = f"{provider}_{tier}_model"
    if (pc.get("models") or {}).get(override_key):
        return pc["models"][override_key]
    # Fall back to built-in defaults
    return PROVIDERS.get(provider, {}).get("models", {}).get(tier, "")


def _tier_for_task(task: str, pc: Optional[dict] = None) -> str:
    """Get the model tier for a task (user's per-module override in Settings first)."""
    pc = pc if pc is not None else get_provider_config()
    module_tiers = pc.get("module_tiers") or {}
    task = task or "default"
    for name in (task, _TASK_ALIASES.get(task)):
        if name and module_tiers.get(name) in ("fast", "full"):
            return module_tiers[name]
    canonical = _TASK_ALIASES.get(task, task)
    return TASK_TIERS.get(canonical, TASK_TIERS.get(task, "full"))


# ── Error handling (never leak keys, surface provider messages) ───────────────

class LLMError(ValueError):
    """Provider error whose message is safe to show to the user (no secrets)."""


def _secrets(pc: dict) -> list:
    vals = [pc.get(k, "") for k in ("claude_key", "openai_key", "gemini_key", "groq_key")]
    try:
        vals.append(cfg.get_api_key())
    except Exception:
        pass
    return [v for v in vals if v and len(v) >= 4]


def scrub(text: str, pc: Optional[dict] = None) -> str:
    """Remove any configured API key (and key=... query params) from a string."""
    if pc is None:
        try:
            pc = get_provider_config()
        except Exception:
            pc = {}
    text = str(text or "")
    for secret in _secrets(pc):
        text = text.replace(secret, "***")
    return re.sub(r"([?&]key=)[^&\s\"']+", r"\1***", text)


def _provider_error(provider: str, r: httpx.Response, pc: dict) -> LLMError:
    msg = ""
    try:
        data = r.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = err.get("message") or err.get("type") or ""
        elif isinstance(err, str):
            msg = err
        elif isinstance(data, dict):
            msg = str(data.get("message", ""))
    except Exception:
        msg = r.text[:300]
    return LLMError(scrub(f"{provider} API error {r.status_code}: {msg or r.reason_phrase}", pc))


async def _post(provider: str, url: str, pc: dict, *, timeout: float = 120, **kwargs) -> httpx.Response:
    """POST wrapper; network exceptions are re-raised without URL/header details."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(url, **kwargs)
    except httpx.TimeoutException:
        raise LLMError(f"{provider}: request timed out.") from None
    except httpx.HTTPError as e:
        raise LLMError(f"{provider}: network error ({type(e).__name__}).") from None


# ── PDF → text extraction ─────────────────────────────────────────────────────

def _pdf_bytes_to_text(pdf_bytes: bytes, max_chars: int = 12000) -> str:
    import pdfplumber
    parts = []
    total = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total >= max_chars:
                break
    return "\n".join(parts)[:max_chars]


async def _pdf_text_async(pdf_bytes: bytes, max_chars: int = 12000) -> str:
    """pdfplumber is CPU-bound — run it off the event loop."""
    return await asyncio.to_thread(_pdf_bytes_to_text, pdf_bytes, max_chars)


# ── Main call function ────────────────────────────────────────────────────────

async def call_llm(
    system: str,
    user_text: str,
    pdf_bytes: Optional[bytes] = None,
    max_tokens: int = 1800,
    task: str = "default",
) -> str:
    """
    Send a prompt to the configured LLM provider.

    Args:
        system:     System prompt
        user_text:  User message text
        pdf_bytes:  Optional raw PDF bytes
        max_tokens: Max response tokens
        task:       Task identifier for model tier selection
                    (screening, decisions, review_quality, blind, etc.)
    """
    pc = get_provider_config()
    provider = pc.get("provider", "claude")
    tier = _tier_for_task(task, pc)

    try:
        if provider == "claude":
            return await _call_claude(system, user_text, pdf_bytes, max_tokens, pc, tier)
        elif provider == "openai":
            return await _call_openai(system, user_text, pdf_bytes, max_tokens, pc, tier)
        elif provider == "gemini":
            return await _call_gemini(system, user_text, pdf_bytes, max_tokens, pc, tier)
        elif provider == "groq":
            return await _call_groq(system, user_text, pdf_bytes, max_tokens, pc, tier)
        elif provider == "ollama":
            return await _call_ollama(system, user_text, pdf_bytes, max_tokens, pc, tier)
        else:
            raise LLMError(f"Unknown provider: {provider}")
    except LLMError:
        raise
    except Exception as e:
        # Any other exception: make sure its message can never carry a key.
        raise LLMError(scrub(f"{provider}: {type(e).__name__}: {e}", pc)) from None


# ── Claude ────────────────────────────────────────────────────────────────────

async def _call_claude(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = pc.get("claude_key") or cfg.get_api_key()
    if not key:
        raise LLMError("Claude API key not configured.")
    model = _model_for("claude", tier, pc)

    content = []
    if pdf_bytes:
        # Base64 PDF document block, placed before the text prompt.
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.b64encode(pdf_bytes).decode()}
        })
    content.append({"type": "text", "text": user_text})

    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": content}]}
    if system:
        payload["system"] = system
    r = await _post(
        "Claude", "https://api.anthropic.com/v1/messages", pc,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json=payload,
    )
    if not r.is_success:
        raise _provider_error("Claude", r, pc)
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


# ── OpenAI ────────────────────────────────────────────────────────────────────

async def _call_openai(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = (pc.get("openai_key") or "").strip()
    if not key:
        raise LLMError("OpenAI API key not configured.")
    model = _model_for("openai", tier, pc)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def _send(user_content):
        return await _post(
            "OpenAI", "https://api.openai.com/v1/chat/completions", pc,
            headers=headers,
            # Current OpenAI (reasoning) models require max_completion_tokens.
            json={"model": model, "max_completion_tokens": max_tokens,
                  "messages": [
                      {"role": "system", "content": system},
                      {"role": "user",   "content": user_content},
                  ]},
        )

    if pdf_bytes:
        b64 = base64.b64encode(pdf_bytes).decode()
        r = await _send([
            {"type": "file", "file": {"filename": "paper.pdf",
                                      "file_data": f"data:application/pdf;base64,{b64}"}},
            {"type": "text", "text": user_text},
        ])
        if r.status_code == 400:
            # Model may not accept file input — fall back to extracted text.
            extracted = await _pdf_text_async(pdf_bytes)
            r = await _send(f"[Paper content]\n{extracted}\n\n{user_text}")
    else:
        r = await _send(user_text)

    if not r.is_success:
        raise _provider_error("OpenAI", r, pc)
    return r.json()["choices"][0]["message"].get("content") or ""


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _call_gemini(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = (pc.get("gemini_key") or "").strip()
    if not key:
        raise LLMError("Gemini API key not configured.")
    model = _model_for("gemini", tier, pc)

    parts = []
    if pdf_bytes:
        parts.append({"inline_data": {"mime_type": "application/pdf",
                                       "data": base64.b64encode(pdf_bytes).decode()}})
    parts.append({"text": user_text})

    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    # Key goes in a header, never in the URL (URLs end up in exception messages/logs).
    r = await _post(
        "Gemini",
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        pc,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        json=body,
    )
    if not r.is_success:
        raise _provider_error("Gemini", r, pc)
    candidates = r.json().get("candidates", [])
    if not candidates:
        raise LLMError("Gemini returned no candidates")
    return "".join(p.get("text", "") for p in (candidates[0].get("content") or {}).get("parts", []))


# ── Groq ──────────────────────────────────────────────────────────────────────

async def _call_groq(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = (pc.get("groq_key") or "").strip()
    if not key:
        raise LLMError("Groq API key not configured.")
    model = _model_for("groq", tier, pc)

    full_text = user_text
    if pdf_bytes:
        extracted = await _pdf_text_async(pdf_bytes)
        full_text = f"[Paper content]\n{extracted}\n\n{user_text}"

    r = await _post(
        "Groq", "https://api.groq.com/openai/v1/chat/completions", pc,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [
                  {"role": "system", "content": system},
                  {"role": "user",   "content": full_text},
              ]},
    )
    if not r.is_success:
        raise _provider_error("Groq", r, pc)
    return r.json()["choices"][0]["message"].get("content") or ""


# ── Ollama ────────────────────────────────────────────────────────────────────

async def _call_ollama(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    base_url = (pc.get("ollama_url") or "http://localhost:11434").rstrip("/")
    model = _model_for("ollama", tier, pc)

    full_text = user_text
    if pdf_bytes:
        extracted = await _pdf_text_async(pdf_bytes)
        full_text = f"[Paper content]\n{extracted}\n\n{user_text}"

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{base_url}/api/chat",
                json={"model": model, "stream": False,
                      "options": {"num_predict": max_tokens},
                      "messages": [
                          {"role": "system", "content": system},
                          {"role": "user",   "content": full_text},
                      ]}
            )
    except httpx.ConnectError:
        raise LLMError(f"Cannot connect to Ollama at {base_url}.") from None
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama: network error ({type(e).__name__}).") from None
    if r.status_code == 404:
        raise LLMError(f"Model '{model}' not found. Run: ollama pull {model}")
    if not r.is_success:
        raise _provider_error("Ollama", r, pc)
    return r.json()["message"]["content"]


# ── Health check ──────────────────────────────────────────────────────────────

async def check_provider_health() -> dict:
    provider = get_active_provider()
    try:
        result = await call_llm(
            system="Reply with exactly: OK",
            user_text="Reply with exactly: OK",
            max_tokens=256,  # headroom for providers that count reasoning tokens
            task="default",
        )
        return {"provider": provider, "ok": "OK" in result, "response": result.strip()}
    except Exception as e:
        return {"provider": provider, "ok": False, "error": scrub(str(e))}
