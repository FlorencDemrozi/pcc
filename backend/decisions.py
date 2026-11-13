"""
decisions.py — LLM-based paper decision support.
Reads reviews (any format), groups by paper, asks LLM for decisions.
Outputs structured results + downloadable CSV/XLSX.
"""

import io
import csv
import json
import asyncio
from typing import Optional
import llm_provider


# ── Decision options ──────────────────────────────────────────────────────────

DECISIONS = [
    "Strong Accept",
    "Accept",
    "Weak Accept",
    "Borderline",
    "Weak Reject",
    "Reject",
    "Strong Reject",
]


# ── Group reviews by paper ────────────────────────────────────────────────────

def group_reviews_by_paper(
    review_rows: list[dict],
    submission_rows: list[dict],
) -> dict[str, dict]:
    """
    Group review rows by paper ID.
    Returns dict: paper_id → {title, authors, track, reviews: [...]}
    """
    # Build submission index — try every possible ID field
    sub_index = {}
    for row in submission_rows:
        for key in ["#", "id", "ID", "paper_id", "submission_id", "Paper ID", "PaperID"]:
            val = str(row.get(key, "") or "").strip()
            if val:
                sub_index[val] = row
                break

    papers = {}

    for rv in review_rows:
        # Find paper ID in review row
        pid = ""
        for key in ["paper_id", "paper", "Paper", "#", "id", "ID",
                    "submission", "submission_id", "Paper ID"]:
            val = str(rv.get(key, "") or "").strip()
            if val:
                pid = val
                break

        if not pid:
            pid = "unknown"

        if pid not in papers:
            sub = sub_index.get(pid, {})
            # Extract title — try many field names
            title = ""
            for k in ["title", "Title", "TITLE", "paper_title", "Paper Title"]:
                title = str(sub.get(k, "") or "").strip()
                if title:
                    break
            # Extract authors
            authors = ""
            for k in ["authors", "Authors", "AUTHORS", "author", "Author"]:
                authors = str(sub.get(k, "") or "").strip()
                if authors:
                    break
            # Extract track
            track = ""
            for k in ["track", "Track", "TRACK"]:
                track = str(sub.get(k, "") or "").strip()
                if track:
                    break

            papers[pid] = {
                "paper_id": pid,
                "title": title or f"Paper #{pid}",
                "authors": authors,
                "track": track,
                "reviews": [],
            }

        papers[pid]["reviews"].append(rv)

    return papers


# ── LLM decision per paper ────────────────────────────────────────────────────

async def decide_paper(
    paper: dict,
    custom_prompt: str = "",
) -> dict:
    """
    Ask the LLM to make a decision on one paper based on its reviews.
    Returns dict with decision, confidence, rationale, key_points.
    """
    reviews = paper["reviews"]

    # Format reviews for the LLM — let it figure out the structure
    review_texts = []
    for i, rv in enumerate(reviews):
        # Build a readable representation of each review
        parts = [f"Review {i+1}:"]
        for k, v in rv.items():
            if v and str(v).strip() and k not in ("paper_id", "paper", "Paper", "#"):
                parts.append(f"  {k}: {v}")
        review_texts.append("\n".join(parts))

    reviews_block = "\n\n".join(review_texts)

    custom_instruction = ""
    if custom_prompt.strip():
        custom_instruction = f"""
CUSTOM DECISION CRITERIA FROM PROGRAM CHAIR:
{custom_prompt.strip()}

Apply these criteria when making your decision.
"""

    system = f"""You are an expert Program Chair making final decisions on conference paper submissions.

You will be given a paper's details and its peer reviews. Analyse all reviews carefully and make a final decision.
{custom_instruction}
Available decisions (choose the most appropriate):
- Strong Accept: exceptional paper, clear contribution, strong reviews
- Accept: solid paper, meets conference standards, positive reviews
- Weak Accept: acceptable paper with minor issues, slightly positive reviews  
- Borderline: mixed reviews, unclear verdict, needs discussion
- Weak Reject: below conference standards, mostly negative reviews
- Reject: significant flaws, negative reviews
- Strong Reject: fundamental problems, very negative reviews

Return ONLY a JSON object (no markdown):
{{
  "decision": "Accept",
  "confidence": "High",
  "rationale": "2-3 sentence explanation of the decision",
  "key_strengths": ["strength 1", "strength 2"],
  "key_weaknesses": ["weakness 1", "weakness 2"],
  "requires_discussion": false,
  "discussion_reason": ""
}}

confidence must be: "High" | "Medium" | "Low"
requires_discussion: true if reviewers strongly disagree or scores are very mixed"""

    user_text = f"""Paper ID: {paper['paper_id']}
Title: {paper['title']}
Authors: {paper['authors'] or 'N/A'}
Track: {paper['track'] or 'N/A'}

Reviews:
{reviews_block}

Make a final decision based on these reviews."""

    try:
        raw = await llm_provider.call_llm(
            system=system,
            user_text=user_text,
            max_tokens=800,
            task="decisions",
        )
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("LLM did not return a JSON object")
        result["key_strengths"] = _as_list(result.get("key_strengths"))
        result["key_weaknesses"] = _as_list(result.get("key_weaknesses"))
        for k in ("decision", "confidence", "rationale", "discussion_reason"):
            if result.get(k) is None:
                result[k] = ""
        result["requires_discussion"] = bool(result.get("requires_discussion"))
        result["paper_id"] = paper["paper_id"]
        result["title"] = paper["title"]
        result["authors"] = paper["authors"]
        result["track"] = paper["track"]
        result["review_count"] = len(reviews)
        return result
    except Exception as e:
        return {
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "authors": paper["authors"],
            "track": paper["track"],
            "review_count": len(reviews),
            "decision": "Error",
            "confidence": "Low",
            "rationale": f"Processing error: {str(e)[:200]}",
            "key_strengths": [],
            "key_weaknesses": [],
            "requires_discussion": False,
            "discussion_reason": "",
        }


# ── Export helpers ────────────────────────────────────────────────────────────

def _as_list(v) -> list[str]:
    """Coerce an LLM field that should be a list of strings (may be None,
    a single string, or contain non-strings)."""
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if x is not None and str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


def _join(v, sep: str = "; ") -> str:
    return sep.join(_as_list(v))


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _safe_cell(v):
    """Neutralise spreadsheet formula injection: strings starting with
    = + - @ (or control chars) are prefixed with an apostrophe."""
    if v is None:
        return ""
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if s and s.startswith(_FORMULA_PREFIXES):
        return "'" + s
    return s


# ── Export to CSV bytes ───────────────────────────────────────────────────────

def decisions_to_csv(decisions: list[dict]) -> bytes:
    """Export decisions list to CSV bytes."""
    if not decisions:
        return b""
    fieldnames = [
        "paper_id", "title", "authors", "track",
        "decision", "confidence", "review_count",
        "requires_discussion", "rationale",
        "key_strengths", "key_weaknesses", "discussion_reason",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for d in decisions:
        row = dict(d)
        row["key_strengths"] = _join(d.get("key_strengths"))
        row["key_weaknesses"] = _join(d.get("key_weaknesses"))
        writer.writerow({k: _safe_cell(row.get(k)) for k in fieldnames})
    return buf.getvalue().encode("utf-8-sig")


def decisions_to_xlsx(decisions: list[dict]) -> bytes:
    """Export decisions list to XLSX bytes."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Decisions"

    headers = [
        "Paper ID", "Title", "Authors", "Track",
        "Decision", "Confidence", "Reviews",
        "Requires Discussion", "Rationale",
        "Key Strengths", "Key Weaknesses",
    ]

    # Decision colour map
    decision_colors = {
        "Strong Accept": "1a7a4a",
        "Accept":        "27ae60",
        "Weak Accept":   "82c983",
        "Borderline":    "f39c12",
        "Weak Reject":   "e67e22",
        "Reject":        "e74c3c",
        "Strong Reject": "922b21",
    }

    # Header row
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1e293b")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    # Data rows
    for row_idx, d in enumerate(decisions, 2):
        values = [
            d.get("paper_id", ""),
            d.get("title", ""),
            d.get("authors", ""),
            d.get("track", ""),
            d.get("decision", ""),
            d.get("confidence", ""),
            d.get("review_count", ""),
            "Yes" if d.get("requires_discussion") else "No",
            d.get("rationale", ""),
            _join(d.get("key_strengths")),
            _join(d.get("key_weaknesses")),
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col)
            safe = _safe_cell(val)
            cell.value = safe
            if isinstance(safe, str):
                cell.data_type = "s"   # never interpret as a formula
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            # Colour the decision cell
            if col == 5:  # Decision column
                color = decision_colors.get(str(val), "64748b")
                cell.fill = PatternFill("solid", fgColor=color)
                cell.font = Font(bold=True, color="FFFFFF")

    # Column widths
    widths = [10, 40, 30, 15, 16, 12, 8, 10, 50, 30, 30]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Freeze header
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
