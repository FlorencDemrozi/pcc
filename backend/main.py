"""
main.py — FastAPI backend for Program Chair Copilot.
Key fix: /api/llm reads a "task" field and enforces the correct feature gate.
"""

import io, json, os, sys, csv, webbrowser, threading, re
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
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
import trial as trial_mod

app = FastAPI(title="Program Chair Copilot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

def _frontend_dir() -> Optional[Path]:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent
    c = base / "frontend" / "dist"
    return c if c.exists() else None

_frontend = _frontend_dir()
if _frontend:
    app.mount("/assets", StaticFiles(directory=str(_frontend / "assets")), name="assets")

async def _parse_tabular(file: UploadFile) -> list[dict]:
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    elif name.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows: return []
            headers = [str(h or "").strip() for h in rows[0]]
            return [{headers[i]: str(v or "").strip() for i, v in enumerate(row)} for row in rows[1:]]
        except ImportError:
            raise HTTPException(500, "openpyxl not installed")
    raise HTTPException(400, f"Unsupported file type: {file.filename}")

# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config(): return config.load()

@app.post("/api/config")
async def save_config(body: dict): return {"ok": config.save(body)}

@app.get("/api/config/apikey")
def get_api_key():
    key = config.get_api_key()
    masked = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else "*" * len(key)
    return {"set": bool(key), "masked": masked}

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
):
    content = await file.read()
    try: notices = json.loads(copyright_notices) if copyright_notices else []
    except: notices = []
    author_names = None
    if camera_ready and author_list_json:
        try:
            author_rows = json.loads(author_list_json)
            m = re.search(r'[_\-](\d{4,})', file.filename or "")
            if m:
                pid = m.group(1)
                author_names = [
                    str(r.get("name") or r.get("author") or r.get("Author") or "").strip()
                    for r in author_rows
                    if str(r.get("paper_id") or r.get("#") or "").strip() == pid
                    and (r.get("name") or r.get("author") or r.get("Author"))
                ]
        except: pass
    result = await pdf_checker.check_pdf_async(
        file_bytes=content, filename=file.filename or "unknown.pdf",
        max_pages=max_pages, double_blind=double_blind,
        copyright_strings=notices, check_camera_ready=camera_ready,
        expected_layout=expected_layout, validation_stamp=validation_stamp,
        use_llm_blind=use_llm_blind, author_names=author_names,
    )
    return pdf_checker.report_to_dict(result)

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
    except: tracks = req_fields = None
    result = meta_checker.check_metadata(
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
    rc = await reviews_file.read()
    review_rows = await file_parser.parse_any_file(rc, reviews_file.filename or "reviews", purpose="review scores", use_llm_fallback=False)
    submission_rows = []
    if submissions_file:
        sc = await submissions_file.read()
        submission_rows = await file_parser.parse_any_file(sc, submissions_file.filename or "submissions", purpose="paper IDs", use_llm_fallback=False)
    assignment_rows = []
    if assignments_file:
        ac = await assignments_file.read()
        assignment_rows = await file_parser.parse_any_file(ac, assignments_file.filename or "assignments", purpose="assignments", use_llm_fallback=False)
    result = review_stats.compute_stats(
        review_rows=review_rows, submission_rows=submission_rows, assignment_rows=assignment_rows,
        min_reviews_per_paper=min_reviews_per_paper, max_load_per_reviewer=max_load_per_reviewer,
        high_variance_threshold=high_variance_threshold,
    )
    return review_stats.report_to_dict(result)

# ── LLM config ────────────────────────────────────────────────────────────────

class LLMConfigBody(BaseModel):
    provider: str; claude_key: str = ""; openai_key: str = ""
    gemini_key: str = ""; groq_key: str = ""; ollama_url: str = "http://localhost:11434"; models: dict = {}

@app.get("/api/config/llm")
def get_llm_config():
    cfg = config.get_llm_config()
    def mask(k): return ("*"*(len(k)-4)+k[-4:]) if len(k)>4 else "*"*len(k)
    return {
        "provider": cfg.get("provider","claude"),
        "claude_key_set": bool(cfg.get("claude_key")), "claude_key_masked": mask(cfg.get("claude_key","")),
        "openai_key_set": bool(cfg.get("openai_key")), "openai_key_masked": mask(cfg.get("openai_key","")),
        "gemini_key_set": bool(cfg.get("gemini_key")), "gemini_key_masked": mask(cfg.get("gemini_key","")),
        "groq_key_set":   bool(cfg.get("groq_key")),   "groq_key_masked":   mask(cfg.get("groq_key","")),
        "ollama_url": cfg.get("ollama_url","http://localhost:11434"), "models": cfg.get("models",{}),
    }

@app.post("/api/config/llm")
async def save_llm_config(body: LLMConfigBody): return {"ok": config.set_llm_config(body.dict())}

@app.get("/api/config/llm/providers")
def list_providers(): return llm_provider.PROVIDERS

@app.post("/api/config/llm/test")
async def test_provider(): return await llm_provider.check_provider_health()

# ── LLM proxy — FIXED: uses "task" field to enforce correct feature gate ──────

_TASK_FEATURE = {
    "screening": "screening", "reviews": "reviews", "decisions": "decisions",
    "program": "program",     "emails": "emails",   "config": "config",
}

@app.post("/api/llm")
async def llm_proxy(body: dict):
    task    = body.get("task", "screening")
    feature = _TASK_FEATURE.get(task, "screening")
    trial_mod.require_full_access(feature)

    system     = body.get("system", "")
    user_text  = body.get("user_text", "")
    pdf_b64    = body.get("pdf_b64")
    max_tokens = body.get("max_tokens", 1800)

    pdf_bytes = None
    if pdf_b64:
        import base64
        pdf_bytes = base64.b64decode(pdf_b64)

    try:
        result = await llm_provider.call_llm(system=system, user_text=user_text, pdf_bytes=pdf_bytes, max_tokens=max_tokens)
        return {"text": result}
    except Exception as e:
        raise HTTPException(400, str(e))

# Backwards-compat alias
@app.post("/api/claude")
async def claude_proxy_compat(body: dict):
    trial_mod.require_full_access("screening")
    api_key = config.get_api_key()
    if not api_key: raise HTTPException(400, "API key not configured.")
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body,
        )
    if response.status_code != 200: raise HTTPException(response.status_code, response.text)
    return response.json()

# ── COI checker ───────────────────────────────────────────────────────────────

@app.post("/api/check/coi")
async def check_coi(
    submissions_file: UploadFile = File(...), tpc_file: UploadFile = File(...),
    author_list_file: Optional[UploadFile] = File(None),
    extra_synonyms: str = Form(""), fuzzy_threshold: int = Form(75),
    use_ror: bool = Form(True), use_llm_expand: bool = Form(True),
):
    try:
        sub_content = await submissions_file.read()
        tpc_content = await tpc_file.read()
        submission_rows = await file_parser.parse_any_file(sub_content, submissions_file.filename or "submissions", purpose="paper ID, title, authors", use_llm_fallback=False)
        tpc_rows = await file_parser.parse_any_file(tpc_content, tpc_file.filename or "tpc_members", purpose="TPC member name, email, affiliation", use_llm_fallback=False)
        author_rows = None
        if author_list_file:
            auth_content = await author_list_file.read()
            author_rows = await file_parser.parse_any_file(auth_content, author_list_file.filename or "author_list", purpose="paper ID, author name, email, affiliation", use_llm_fallback=False)
        if not submission_rows: raise HTTPException(400, "Could not parse submissions file.")
        if not tpc_rows: raise HTTPException(400, "Could not parse TPC members file.")
        try: synonyms = json.loads(extra_synonyms) if extra_synonyms else {}
        except: synonyms = {}
        result = await coi_checker.check_coi_async(
            submission_rows=submission_rows, tpc_rows=tpc_rows, author_rows=author_rows,
            extra_synonyms=synonyms, fuzzy_threshold=fuzzy_threshold, use_ror=use_ror, use_llm=use_llm_expand,
        )
        return coi_checker.report_to_dict(result)
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"COI check failed: {str(e)}")

# ── Decisions ─────────────────────────────────────────────────────────────────

@app.post("/api/decisions/run")
async def run_decisions(
    reviews_file: UploadFile = File(...),
    submissions_file: Optional[UploadFile] = File(None),
    custom_prompt: str = Form(""),
):
    trial_mod.require_full_access("decisions")
    rev_content = await reviews_file.read()
    review_rows = await file_parser.parse_any_file(rev_content, reviews_file.filename or "reviews", purpose="paper ID, reviewer, score, review text", use_llm_fallback=False)
    submission_rows = []
    if submissions_file:
        sub_content = await submissions_file.read()
        submission_rows = await file_parser.parse_any_file(sub_content, submissions_file.filename or "submissions", purpose="paper ID, title, authors", use_llm_fallback=False)
    papers = decisions_mod.group_reviews_by_paper(review_rows, submission_rows)
    results = [await decisions_mod.decide_paper(paper, custom_prompt) for paper in papers.values()]
    return {"decisions": results, "total": len(results)}

@app.post("/api/decisions/export/csv")
async def export_decisions_csv(body: dict):
    return Response(content=decisions_mod.decisions_to_csv(body.get("decisions", [])), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=decisions.csv"})

@app.post("/api/decisions/export/xlsx")
async def export_decisions_xlsx(body: dict):
    return Response(content=decisions_mod.decisions_to_xlsx(body.get("decisions", [])), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=decisions.xlsx"})

# ── Parse reviews ─────────────────────────────────────────────────────────────

@app.post("/api/parse/reviews")
async def parse_reviews(reviews_file: UploadFile = File(...)):
    content = await reviews_file.read()
    rows = await file_parser.parse_any_file(content, reviews_file.filename or "reviews", purpose="paper ID, reviewer, score, review text", use_llm_fallback=False)
    return [{k: str(v or "").replace("\r\n"," ").replace("\r"," ").replace("\n"," ").strip() for k,v in row.items() if not k.startswith("_")} for row in rows]

# ── Trial & health ────────────────────────────────────────────────────────────

@app.get("/api/trial")
def get_trial(): return trial_mod.get_trial_status()

@app.get("/api/health")
def health(): return {"status": "ok", "api_key_set": bool(config.get_api_key()), "version": "1.0.0"}

@app.post("/api/quit")
def quit_app():
    def _shutdown():
        import time; time.sleep(0.5)
        try:
            import signal; os.kill(os.getpid(), signal.SIGTERM)
        except: pass
        time.sleep(0.3); os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()
    return {"ok": True}

# ── Frontend SPA catch-all ────────────────────────────────────────────────────

@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
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
        import time; time.sleep(1.5); webbrowser.open("http://localhost:8000")

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
