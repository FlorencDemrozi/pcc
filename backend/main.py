"""
main.py — FastAPI backend for Program Chair Copilot.
All features are free and unrestricted. The server only listens on 127.0.0.1
and rejects requests that do not come from a local origin.
"""

import asyncio, base64, binascii, io, json, os, sys, webbrowser, threading, re
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel
import httpx

import config
import pdf_checker
import meta_checker
import review_stats
import coi_checker
import llm_provider
import file_parser
import decisions as decisions_mod
import references as references_mod
import hashlib
from collections import OrderedDict

PORT = int(os.environ.get("PCC_PORT", "8000"))
MAX_UPLOAD_BYTES = 200 * 1024 * 1024          # 200 MB per request
MAX_LLM_TOKENS = 16000
DECISION_CONCURRENCY = 4

# Extracted paper text, keyed by SHA-256 of the PDF bytes. Filled by the
# compliance check so later LLM calls (AI screening in "text" mode) reuse it
# instead of re-extracting, and can send text instead of the whole PDF.
_TEXT_CACHE: "OrderedDict[str, str]" = OrderedDict()
_TEXT_CACHE_MAX = 1000
_text_cache_lock = threading.Lock()

def _cache_text(pdf_bytes: bytes, text: str) -> None:
    key = hashlib.sha256(pdf_bytes).hexdigest()
    with _text_cache_lock:
        _TEXT_CACHE[key] = text
        _TEXT_CACHE.move_to_end(key)
        while len(_TEXT_CACHE) > _TEXT_CACHE_MAX:
            _TEXT_CACHE.popitem(last=False)

async def _paper_text(pdf_bytes: bytes) -> tuple[str, bool]:
    """(text, from_cache)."""
    key = hashlib.sha256(pdf_bytes).hexdigest()
    with _text_cache_lock:
        if key in _TEXT_CACHE:
            return _TEXT_CACHE[key], True
    text = await asyncio.to_thread(references_mod.extract_reading_text_from_bytes, pdf_bytes)
    _cache_text(pdf_bytes, text)
    return text, False

app = FastAPI(title="Program Chair Copilot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"],
    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"],
)

# ── Local-only hardening ──────────────────────────────────────────────────────
# 1. Host header must be a loopback name (blocks DNS-rebinding attacks).
# 2. State-changing requests carrying an Origin header must come from a local
#    http origin on any port (the packaged app on :8000, the Vite dev server on
#    :5173 — Vite's proxy forwards the browser's Origin unchanged).
# 3. Request bodies larger than MAX_UPLOAD_BYTES are refused with 413.

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?$", re.IGNORECASE)
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def _host_name(host_header: str) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):                      # [::1]:8000
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


@app.middleware("http")
async def local_only_guard(request: Request, call_next):
    if _host_name(request.headers.get("host", "")) not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    if request.method.upper() in _STATE_CHANGING:
        origin = request.headers.get("origin")
        if origin is not None and not _LOCAL_ORIGIN.match(origin.strip()):
            return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_UPLOAD_BYTES:
                return JSONResponse(
                    {"detail": f"Upload too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB per request)."},
                    status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    return await call_next(request)


@app.exception_handler(file_parser.UnsupportedFileError)
async def _unsupported_file(_request: Request, exc: file_parser.UnsupportedFileError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def _frontend_dir() -> Optional[Path]:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent
    c = base / "frontend" / "dist"
    return c if c.exists() else None

_frontend = _frontend_dir()
if _frontend and (_frontend / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend / "assets")), name="assets")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _read_upload(file: UploadFile) -> bytes:
    """Read an upload, enforcing the size limit even without Content-Length."""
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"'{file.filename}' is too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"'{file.filename}' is too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    return data


async def _parse_upload(file: UploadFile, default_name: str, purpose: str) -> list[dict]:
    content = await _read_upload(file)
    return await file_parser.parse_any_file(content, file.filename or default_name,
                                            purpose=purpose, use_llm_fallback=False)


async def _run_coro_in_thread(fn, *args, **kwargs):
    """
    Run an async analyser (whose body does blocking CPU/IO work before awaiting)
    on a worker thread with its own event loop, so the server loop stays free.
    """
    return await asyncio.to_thread(lambda: asyncio.run(fn(*args, **kwargs)))


def _parse_tabular_sync(content: bytes, filename: str) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith(".xls"):
        raise HTTPException(400, f"'{filename}' is an old .xls Excel file. Please re-save as .xlsx or .csv.")
    if name.endswith((".csv", ".tsv")):
        return file_parser.parse_csv_bytes(content)
    if name.endswith((".xlsx", ".xlsm")):
        return file_parser.parse_xlsx_bytes(content)
    raise HTTPException(400, f"Unsupported file type: {filename}. Please upload .csv or .xlsx.")


async def _parse_tabular(file: UploadFile) -> list[dict]:
    content = await _read_upload(file)
    return await asyncio.to_thread(_parse_tabular_sync, content, file.filename or "")


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    # API keys are never returned in plaintext — only *_set / *_masked flags.
    return config.redacted(config.load())

@app.post("/api/config")
async def save_config(body: dict):
    # The llm block (and its keys) only goes through the merge logic;
    # the legacy top-level key cannot be overwritten from here.
    return {"ok": config.update_config(body)}

@app.get("/api/config/apikey")
def get_api_key():
    key = config.get_api_key()
    return {"set": bool(key), "masked": config.mask(key)}

class ApiKeyBody(BaseModel):
    key: str

@app.post("/api/config/apikey")
def set_api_key(body: ApiKeyBody): return {"ok": config.set_api_key(body.key)}

@app.get("/api/config/conference")
def get_conference(): return config.get_conference()

@app.post("/api/config/conference")
async def save_conference(body: dict): return {"ok": config.set_conference(body)}

# ── PDF checker ───────────────────────────────────────────────────────────────

@app.post("/api/check/pdf")
async def check_pdf(
    file: UploadFile = File(...),
    max_pages: int = Form(6),
    double_blind: bool = Form(True),
    copyright_notices: str = Form(""),
    camera_ready: bool = Form(False),
    expected_layout: str = Form("any"),
    validation_stamp: str = Form(""),
    use_llm_blind: bool = Form(False),
    author_list_json: str = Form(""),
    refs_excluded: bool = Form(False),
):
    content = await _read_upload(file)
    try: notices = json.loads(copyright_notices) if copyright_notices else []
    except Exception: notices = []
    author_names = None
    if author_list_json:  # used by the blind check and the camera-ready author check
        try:
            author_rows = json.loads(author_list_json)
            known = {str(r.get("paper_id") or r.get("#") or "").strip() for r in author_rows}
            nums = re.findall(r'\d+', file.filename or "")
            pid = next((n for n in reversed(nums) if n in known or n.lstrip("0") in known), None)
            if pid:
                pid = pid if pid in known else pid.lstrip("0")
                author_names = [
                    str(r.get("name") or r.get("author") or r.get("Author") or "").strip()
                    for r in author_rows
                    if str(r.get("paper_id") or r.get("#") or "").strip() == pid
                    and (r.get("name") or r.get("author") or r.get("Author"))
                ]
        except Exception: pass
    result = await _run_coro_in_thread(
        pdf_checker.check_pdf_async,
        file_bytes=content, filename=file.filename or "unknown.pdf",
        max_pages=max_pages, double_blind=double_blind,
        copyright_strings=notices, check_camera_ready=camera_ready,
        expected_layout=expected_layout, validation_stamp=validation_stamp,
        use_llm_blind=use_llm_blind, author_names=author_names,
        refs_excluded=refs_excluded,
    )
    if result.reading_text:
        _cache_text(content, result.reading_text)
    return pdf_checker.report_to_dict(result)

# ── Reference verification (opt-in, network) ─────────────────────────────────

@app.post("/api/check/references")
async def check_references(file: UploadFile = File(...), verify: bool = Form(False)):
    """Citation cross-check; with verify=true also looks every reference up in
    Crossref/OpenAlex. Only the reference strings leave the machine."""
    content = await _read_upload(file)
    try:
        text, _ = await _paper_text(content)
    except Exception:
        raise HTTPException(400, "Could not open PDF (encrypted or corrupt).")
    analysis = references_mod.analyse_citations(text)
    out = {k: analysis[k] for k in ("status", "style", "cited_count", "uncited", "missing")}
    out["entries"] = analysis["entries"]
    if verify and analysis["entries"]:
        oa_key = (config.get_llm_config() or {}).get("openalex_key", "")
        results = await references_mod.verify_references(analysis["entries"], openalex_key=oa_key)
        out["verification"] = results
        out["verification_summary"] = {
            s: sum(1 for r in results if r["status"] == s)
            for s in ("verified", "likely", "not_found", "not_checkable", "error")
        }
    return out

# ── Meta checker ──────────────────────────────────────────────────────────────

@app.post("/api/check/meta")
async def check_meta(
    file: UploadFile = File(...),
    min_abstract_words: int = Form(50), max_abstract_words: int = Form(300),
    min_keywords: int = Form(3), max_keywords: int = Form(8),
    valid_tracks: str = Form(""), required_fields: str = Form(""),
):
    rows = await _parse_tabular(file)
    try:
        tracks = json.loads(valid_tracks) if valid_tracks else None
        req_fields = json.loads(required_fields) if required_fields else None
    except Exception: tracks = req_fields = None
    result = await asyncio.to_thread(
        meta_checker.check_metadata,
        rows=rows, required_fields=req_fields,
        min_abstract_words=min_abstract_words, max_abstract_words=max_abstract_words,
        min_keywords=min_keywords, max_keywords=max_keywords, valid_tracks=tracks,
    )
    return meta_checker.report_to_dict(result)

# ── Review statistics ─────────────────────────────────────────────────────────

@app.post("/api/stats/reviews")
async def review_statistics(
    reviews_file: UploadFile = File(...),
    submissions_file: Optional[UploadFile] = File(None),
    assignments_file: Optional[UploadFile] = File(None),
    min_reviews_per_paper: int = Form(3),
    max_load_per_reviewer: int = Form(8),
    high_variance_threshold: float = Form(1.5),
):
    review_rows = await _parse_upload(reviews_file, "reviews", "review scores")
    submission_rows = await _parse_upload(submissions_file, "submissions", "paper IDs") if submissions_file else []
    assignment_rows = await _parse_upload(assignments_file, "assignments", "assignments") if assignments_file else []
    result = await asyncio.to_thread(
        review_stats.compute_stats,
        review_rows=review_rows, submission_rows=submission_rows, assignment_rows=assignment_rows,
        min_reviews_per_paper=min_reviews_per_paper, max_load_per_reviewer=max_load_per_reviewer,
        high_variance_threshold=high_variance_threshold,
    )
    return review_stats.report_to_dict(result)

# ── LLM config ────────────────────────────────────────────────────────────────

class LLMConfigBody(BaseModel):
    # Keys: empty / missing = keep the stored key. Use clear_keys to remove one.
    provider: str = ""
    claude_key: str = ""; openai_key: str = ""; gemini_key: str = ""; groq_key: str = ""
    openalex_key: str = ""   # optional, used only for reference verification
    clear_keys: list[str] = []
    ollama_url: str = ""
    models: dict = {}
    module_tiers: dict = {}   # { moduleName: "fast" | "full" }

@app.get("/api/config/llm")
def get_llm_config():
    cfg = config.get_llm_config()
    out = {
        "provider": cfg.get("provider", "claude"),
        "ollama_url": cfg.get("ollama_url", "http://localhost:11434"),
        "models": cfg.get("models", {}) or {},
        "module_tiers": cfg.get("module_tiers", {}) or {},
    }
    for k in config.KEY_FIELDS:
        val = cfg.get(k, "") or ""
        out[f"{k}_set"] = bool(val)
        out[f"{k}_masked"] = config.mask(val)
    return out

@app.post("/api/config/llm")
async def save_llm_config(body: LLMConfigBody):
    return {"ok": config.set_llm_config(body.model_dump())}

@app.get("/api/config/llm/providers")
def list_providers(): return llm_provider.PROVIDERS

@app.post("/api/config/llm/test")
async def test_provider(): return await llm_provider.check_provider_health()

# ── LLM proxy — "task" selects the model tier (fast/full, per Settings) ───────

@app.post("/api/llm")
async def llm_proxy(body: dict):
    task      = str(body.get("task") or "default")[:64]
    system    = str(body.get("system") or "")
    user_text = str(body.get("user_text") or "")
    pdf_b64   = body.get("pdf_b64")
    pdf_mode  = str(body.get("pdf_mode") or "native")   # "native" | "text"

    raw_max = body.get("max_tokens", 1800)
    try:
        if isinstance(raw_max, bool): raise ValueError
        max_tokens = int(raw_max)
    except (TypeError, ValueError):
        raise HTTPException(400, "max_tokens must be an integer.")
    max_tokens = max(1, min(max_tokens, MAX_LLM_TOKENS))

    pdf_bytes = None
    if pdf_b64:
        if not isinstance(pdf_b64, str):
            raise HTTPException(400, "pdf_b64 must be a base64 string.")
        if pdf_b64.startswith("data:") and "," in pdf_b64:
            pdf_b64 = pdf_b64.split(",", 1)[1]
        try:
            pdf_bytes = base64.b64decode(pdf_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "pdf_b64 is not valid base64.")

    if pdf_bytes is not None and pdf_mode == "text":
        # Cheaper: send the extracted text (reused from the compliance check
        # when available) instead of the whole PDF.
        try:
            text, _ = await _paper_text(pdf_bytes)
        except Exception:
            text = ""
        if text.strip():
            user_text = (f"{user_text}\n\n=== PAPER TEXT (extracted from PDF; figures not included) ===\n"
                         f"{text[:80000]}")
            pdf_bytes = None

    try:
        result = await llm_provider.call_llm(system=system, user_text=user_text, pdf_bytes=pdf_bytes,
                                             max_tokens=max_tokens, task=task)
        return {"text": result}
    except Exception as e:
        raise HTTPException(400, llm_provider.scrub(str(e)))

# Backwards-compat alias
@app.post("/api/claude")
async def claude_proxy_compat(body: dict):
    api_key = config.get_api_key()
    if not api_key: raise HTTPException(400, "API key not configured.")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Claude: network error ({type(e).__name__}).")
    if response.status_code != 200:
        raise HTTPException(response.status_code, llm_provider.scrub(response.text[:2000]))
    return response.json()

# ── COI checker ───────────────────────────────────────────────────────────────

@app.post("/api/check/coi")
async def check_coi(
    submissions_file: UploadFile = File(...), tpc_file: UploadFile = File(...),
    author_list_file: Optional[UploadFile] = File(None),
    extra_synonyms: str = Form(""), fuzzy_threshold: int = Form(75),
    # Network lookups are opt-in: everything runs locally unless the user enables them.
    use_ror: bool = Form(False), use_llm_expand: bool = Form(False),
):
    try:
        submission_rows = await _parse_upload(submissions_file, "submissions", "paper ID, title, authors")
        tpc_rows = await _parse_upload(tpc_file, "tpc_members", "TPC member name, email, affiliation")
        author_rows = None
        if author_list_file:
            author_rows = await _parse_upload(author_list_file, "author_list", "paper ID, author name, email, affiliation")
        if not submission_rows: raise HTTPException(400, "Could not parse submissions file.")
        if not tpc_rows: raise HTTPException(400, "Could not parse TPC members file.")
        try: synonyms = json.loads(extra_synonyms) if extra_synonyms else {}
        except Exception: synonyms = {}
        result = await _run_coro_in_thread(
            coi_checker.check_coi_async,
            submission_rows=submission_rows, tpc_rows=tpc_rows, author_rows=author_rows,
            extra_synonyms=synonyms, fuzzy_threshold=fuzzy_threshold, use_ror=use_ror, use_llm=use_llm_expand,
        )
        return coi_checker.report_to_dict(result)
    except HTTPException: raise
    except file_parser.UnsupportedFileError as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(500, llm_provider.scrub(f"COI check failed: {e}"))

# ── Decisions ─────────────────────────────────────────────────────────────────

@app.post("/api/decisions/run")
async def run_decisions(
    reviews_file: UploadFile = File(...),
    submissions_file: Optional[UploadFile] = File(None),
    custom_prompt: str = Form(""),
):
    review_rows = await _parse_upload(reviews_file, "reviews", "paper ID, reviewer, score, review text")
    submission_rows = []
    if submissions_file:
        submission_rows = await _parse_upload(submissions_file, "submissions", "paper ID, title, authors")
    papers = await asyncio.to_thread(decisions_mod.group_reviews_by_paper, review_rows, submission_rows)

    sem = asyncio.Semaphore(DECISION_CONCURRENCY)
    async def _decide(paper):
        async with sem:
            return await decisions_mod.decide_paper(paper, custom_prompt)
    results = await asyncio.gather(*(_decide(p) for p in papers.values()))
    return {"decisions": list(results), "total": len(results)}

@app.post("/api/decisions/export/csv")
async def export_decisions_csv(body: dict):
    data = await asyncio.to_thread(decisions_mod.decisions_to_csv, body.get("decisions", []))
    return Response(content=data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=decisions.csv"})

@app.post("/api/decisions/export/xlsx")
async def export_decisions_xlsx(body: dict):
    data = await asyncio.to_thread(decisions_mod.decisions_to_xlsx, body.get("decisions", []))
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=decisions.xlsx"})

# ── Parse reviews ─────────────────────────────────────────────────────────────

@app.post("/api/parse/reviews")
async def parse_reviews(reviews_file: UploadFile = File(...)):
    rows = await _parse_upload(reviews_file, "reviews", "paper ID, reviewer, score, review text")
    return [{k: (v if isinstance(v, bool) else str(v or "").replace("\r\n"," ").replace("\r"," ").replace("\n"," ").strip())
             for k, v in row.items() if not k.startswith("_")} for row in rows]

# ── Health & quit ─────────────────────────────────────────────────────────────

@app.get("/api/health")
def health(): return {"status": "ok", "api_key_set": bool(config.get_api_key()), "version": "1.0.0"}

@app.post("/api/quit")
def quit_app():
    # POST-only; covered by the Host/Origin guard above.
    def _shutdown():
        import time; time.sleep(0.5)
        try:
            import signal; os.kill(os.getpid(), signal.SIGTERM)
        except Exception: pass
        time.sleep(0.3); os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()
    return {"ok": True}

# ── Frontend SPA catch-all ────────────────────────────────────────────────────

@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if _frontend is None: return JSONResponse({"error": "Frontend not built"}, status_code=404)
    index = _frontend / "index.html"
    if not index.exists(): return JSONResponse({"error": "index.html not found"}, status_code=404)
    return FileResponse(str(index))

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:
        log_dir = os.path.join(os.path.expanduser("~"), ".pcc")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "pcc.log"), "a", buffering=1, encoding="utf-8")
        if sys.stdout is None: sys.stdout = log_file
        if sys.stderr is None: sys.stderr = log_file

    def _open_browser():
        import time; time.sleep(1.5); webbrowser.open(f"http://localhost:{PORT}")

    if not os.environ.get("PCC_NO_BROWSER"):
        threading.Thread(target=_open_browser, daemon=True).start()
    # Bind to loopback only — never expose the server on the network.
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
