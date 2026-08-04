"""
llm_provider.py — unified LLM call abstraction.
Routes to Claude, OpenAI, Gemini, Groq, or Ollama based on config.
Supports model tiers: 'full' (best model) and 'fast' (cheaper/faster model).
"""

import base64
import io
import json
from typing import Optional
import httpx
import config as cfg


# ── Provider definitions ──────────────────────────────────────────────────────

PROVIDERS = {
    "claude": {
        "name": "Claude (Anthropic)", "pdf": "native",
        "models": {
            "full": "claude-sonnet-4-20250514",
            "fast": "claude-haiku-4-5",
        }
    },
    "openai": {
        "name": "ChatGPT (OpenAI)", "pdf": "vision",
        "models": {
            "full": "gpt-4o",
            "fast": "gpt-4o-mini",
        }
    },
    "gemini": {
        "name": "Gemini (Google)", "pdf": "native",
        "models": {
            "full": "gemini-1.5-pro",
            "fast": "gemini-1.5-flash",
        }
    },
    "groq": {
        "name": "Groq", "pdf": "text",
        "models": {
            "full": "llama-3.1-70b-versatile",
            "fast": "llama-3.1-8b-instant",
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
    "default":      "full",
}


def get_provider_config() -> dict:
    c = cfg.load()
    return c.get("llm", {
        "provider": "claude",
        "claude_key": "",
        "openai_key": "",
        "gemini_key": "",
        "groq_key": "",
        "ollama_url": "http://localhost:11434",
        "models": {},
        "module_tiers": {},  # per-module override: { module_id: "full"|"fast" }
    })


def get_active_provider() -> str:
    return get_provider_config().get("provider", "claude")


def _model_for(provider: str, tier: str = "full") -> str:
    """Get the model name for a provider and tier."""
    pc = get_provider_config()
    # Check for user override first
    override_key = f"{provider}_{tier}_model"
    if pc.get("models", {}).get(override_key):
        return pc["models"][override_key]
    # Fall back to built-in defaults
    return PROVIDERS.get(provider, {}).get("models", {}).get(tier, "")


def _tier_for_task(task: str) -> str:
    """Get the appropriate model tier for a task."""
    pc = get_provider_config()
    # User can override per module in settings
    module_tiers = pc.get("module_tiers", {})
    if task in module_tiers:
        return module_tiers[task]
    return TASK_TIERS.get(task, "full")


# ── PDF → text extraction ─────────────────────────────────────────────────────

def _pdf_bytes_to_text(pdf_bytes: bytes, max_chars: int = 12000) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            parts.append(t)
    return "\n".join(parts)[:max_chars]


def _pdf_to_base64_pages(pdf_bytes: bytes, max_pages: int = 6) -> list[dict]:
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=150, first_page=1, last_page=max_pages)
        result = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            result.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}
            })
        return result
    except Exception:
        text = _pdf_bytes_to_text(pdf_bytes)
        return [{"type": "text", "text": f"[PDF text content]\n{text}"}]


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
    provider = get_active_provider()
    pc = get_provider_config()
    tier = _tier_for_task(task)

    if provider == "claude":
        return await _call_claude(system, user_text, pdf_bytes, max_tokens, pc, tier)
    elif provider == "openai":
        return await _call_openai(system, user_text, pdf_bytes, max_tokens, pc, tier)
    elif provider == "gemini":
        return await _call_gemini(system, user_text, pdf_bytes, max_tokens, pc, tier)
    elif provider == "groq":
        return await _call_groq(system, user_text, pdf_bytes, max_tokens, pc, tier)
    elif provider == "ollama":
        return await _call_ollama(system, user_text, pdf_bytes, max_tokens, pc)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ── Claude ────────────────────────────────────────────────────────────────────

async def _call_claude(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = pc.get("claude_key") or cfg.get_api_key()
    if not key:
        raise ValueError("Claude API key not configured.")
    model = _model_for("claude", tier)

    content = []
    if pdf_bytes:
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.b64encode(pdf_bytes).decode()}
        })
    content.append({"type": "text", "text": user_text})

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "system": system, "messages": [{"role": "user", "content": content}]}
        )
    r.raise_for_status()
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []))


# ── OpenAI ────────────────────────────────────────────────────────────────────

async def _call_openai(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = pc.get("openai_key", "").strip()
    if not key:
        raise ValueError("OpenAI API key not configured.")
    model = _model_for("openai", tier)

    if pdf_bytes:
        image_blocks = _pdf_to_base64_pages(pdf_bytes)
        image_blocks.append({"type": "text", "text": user_text})
        user_content = image_blocks
    else:
        user_content = user_text

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [
                      {"role": "system", "content": system},
                      {"role": "user",   "content": user_content},
                  ]}
        )
    if not r.is_success:
        raise ValueError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _call_gemini(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = pc.get("gemini_key", "")
    if not key:
        raise ValueError("Gemini API key not configured.")
    model = _model_for("gemini", tier)

    parts = []
    if pdf_bytes:
        parts.append({"inline_data": {"mime_type": "application/pdf",
                                       "data": base64.b64encode(pdf_bytes).decode()}})
    parts.append({"text": user_text})

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            headers={"Content-Type": "application/json"},
            json={"system_instruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": parts}],
                  "generationConfig": {"maxOutputTokens": max_tokens}}
        )
    r.raise_for_status()
    candidates = r.json().get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    return "".join(p.get("text", "") for p in candidates[0]["content"]["parts"])


# ── Groq ──────────────────────────────────────────────────────────────────────

async def _call_groq(system, user_text, pdf_bytes, max_tokens, pc, tier="full"):
    key = pc.get("groq_key", "")
    if not key:
        raise ValueError("Groq API key not configured.")
    model = _model_for("groq", tier)

    full_text = user_text
    if pdf_bytes:
        extracted = _pdf_bytes_to_text(pdf_bytes)
        full_text = f"[Paper content]\n{extracted}\n\n{user_text}"

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [
                      {"role": "system", "content": system},
                      {"role": "user",   "content": full_text},
                  ]}
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ── Ollama ────────────────────────────────────────────────────────────────────

async def _call_ollama(system, user_text, pdf_bytes, max_tokens, pc):
    base_url = pc.get("ollama_url", "http://localhost:11434").rstrip("/")
    model = _model_for("ollama", "full")

    full_text = user_text
    if pdf_bytes:
        extracted = _pdf_bytes_to_text(pdf_bytes)
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
        r.raise_for_status()
        return r.json()["message"]["content"]
    except httpx.ConnectError:
        raise ValueError(f"Cannot connect to Ollama at {base_url}.")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Model '{model}' not found. Run: ollama pull {model}")
        raise


# ── Health check ──────────────────────────────────────────────────────────────

async def check_provider_health() -> dict:
    provider = get_active_provider()
    try:
        result = await call_llm(
            system="Reply with exactly: OK",
            user_text="Reply with exactly: OK",
            max_tokens=10,
            task="default",
        )
        return {"provider": provider, "ok": "OK" in result, "response": result.strip()}
    except Exception as e:
        return {"provider": provider, "ok": False, "error": str(e)}
