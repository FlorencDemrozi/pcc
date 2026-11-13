"""
references.py — reference-list analysis for submitted papers.

1. extract_reading_text(pdf)      column-aware full text (also reused for cheap LLM screening)
2. analyse_citations(text)        cross-check in-text citations vs. the reference list
                                  (numeric styles: [1], [2, 5], [3]-[6], [7–9])
3. verify_references(entries)     opt-in network lookup of each entry in Crossref
                                  (and OpenAlex when a free key is configured) to flag
                                  references that cannot be found
                                  (possible hallucinated / mistyped references)

Only reference strings (public bibliographic data) are sent over the network,
never paper text, and only when the user enables verification.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Optional

import httpx
from rapidfuzz import fuzz

# ── Column-aware text extraction ──────────────────────────────────────────────

def _xt(page_or_crop) -> str:
    """extract_text with a font-size-relative word gap; some PDFs (tight
    kerning) otherwise come out as "Materialsforhigh-temperature"."""
    try:
        return page_or_crop.extract_text(x_tolerance_ratio=0.15) or ""
    except TypeError:  # older pdfplumber
        return page_or_crop.extract_text(x_tolerance=1.5) or ""


def _page_reading_text(page) -> str:
    """Text of one page in reading order. For two-column pages, read the left
    column then the right column (pdfplumber's extract_text() interleaves them
    line by line, which mixes body text and references)."""
    from pdf_checker import _detect_column_layout  # local import: avoid cycle
    try:
        if _detect_column_layout(page) == "two-column":
            w, h = float(page.width), float(page.height)
            return _xt(page.crop((0, 0, w / 2, h))) + "\n" + _xt(page.crop((w / 2, 0, w, h)))
        return _xt(page)
    except Exception:
        try:
            return page.extract_text() or ""
        except Exception:
            return ""


def extract_reading_text(pdf) -> str:
    return "\n".join(_page_reading_text(p) for p in pdf.pages)


def extract_reading_text_from_bytes(pdf_bytes: bytes) -> str:
    import io
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return extract_reading_text(pdf)


# ── Splitting body / references ───────────────────────────────────────────────

_HEADING_RE = re.compile(
    r'(?mi)^[ \t]*(?:(?:[IVXLC]{1,6}|\d{1,2}|[A-Z])\s*[.):]?\s+)?'
    r'(?:R\s?E\s?F\s?E\s?R\s?E\s?N\s?C\s?E\s?S?|references?|bibliography|literature\s+cited|works\s+cited)'
    r'[ \t]*:?[ \t]*$'
)


def split_body_references(text: str) -> tuple[str, str]:
    """(body, references). Uses the LAST references heading in the text."""
    last = None
    for m in _HEADING_RE.finditer(text or ""):
        last = m
    if not last:
        return text or "", ""
    return text[: last.start()], text[last.end():]


# ── Parsing entries ───────────────────────────────────────────────────────────

_ENTRY_BRACKET_RE = re.compile(r'(?m)^\s*\[(\d{1,3})\]\s*')
# "[12] R. S. Sangwan" anywhere (start of line or after whitespace), followed by a name/quote
_ENTRY_BRACKET_ANY_RE = re.compile(r'(?:(?<=\s)|^)\[(\d{1,3})\]\s+(?=[A-Z“"‘])', re.MULTILINE)
_ENTRY_NUMBERED_RE = re.compile(r'(?m)^\s*(\d{1,3})[.)]\s+(?=[A-Z])')
# Things that commonly follow the reference list and must not be glued to the last entry
_TRAILER_RE = re.compile(r'(?mi)^\s*(appendix|acknowledg(e)?ments?|biograph(y|ies))\b.*$')


def parse_entries(ref_text: str) -> tuple[str, list[dict]]:
    """Return (style, entries). style: 'numeric' | 'unknown'.
    entries: [{"n": int, "text": str}] in list order."""
    if not ref_text.strip():
        return "unknown", []
    t = _TRAILER_RE.split(ref_text, maxsplit=1)[0] if _TRAILER_RE.search(ref_text) else ref_text
    for rx in (_ENTRY_BRACKET_RE, _ENTRY_NUMBERED_RE):
        marks = list(rx.finditer(t))
        if rx is _ENTRY_BRACKET_RE:
            # Entries can also sit mid-line when two columns get merged
            # ("... detection [13] M. Hnamte ..."): add those, keeping the
            # first occurrence of each number, in text order.
            marks = sorted(marks + list(_ENTRY_BRACKET_ANY_RE.finditer(t)), key=lambda m: m.start())
            seen, uniq = set(), []
            for m in marks:
                if m.group(1) not in seen:
                    seen.add(m.group(1)); uniq.append(m)
            marks = uniq
        if len(marks) >= 2:
            entries = []
            for i, m in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
                body = re.sub(r'\s+', ' ', t[m.end():end]).strip()
                # de-hyphenate line breaks ("compu- tation" -> "computation")
                body = re.sub(r'(\w)- (\w)', r'\1\2', body)
                entries.append({"n": int(m.group(1)), "text": body[:600]})
            return "numeric", entries
    return "unknown", []


# ── In-text citations ─────────────────────────────────────────────────────────

_CITE_GROUP_RE = re.compile(r'\[(\s*\d{1,3}(?:\s*[-–—−]\s*\d{1,3})?(?:\s*[,;]\s*\d{1,3}(?:\s*[-–—−]\s*\d{1,3})?)*\s*)\]')
_CITE_RANGE_PAIR_RE = re.compile(r'\[(\d{1,3})\]\s*[-–—−]\s*\[(\d{1,3})\]')


def cited_numbers(body: str) -> set[int]:
    nums: set[int] = set()
    for a, b in _CITE_RANGE_PAIR_RE.findall(body):
        a, b = int(a), int(b)
        if 0 < a <= b and b - a <= 50:
            nums.update(range(a, b + 1))
    for grp in _CITE_GROUP_RE.findall(body):
        for part in re.split(r'[,;]', grp):
            part = part.strip()
            rng = re.split(r'\s*[-–—−]\s*', part)
            try:
                if len(rng) == 2:
                    a, b = int(rng[0]), int(rng[1])
                    if 0 < a <= b and b - a <= 50:
                        nums.update(range(a, b + 1))
                elif rng[0]:
                    nums.add(int(rng[0]))
            except ValueError:
                pass
    return {n for n in nums if 0 < n <= 500}


def analyse_citations(text: str) -> dict:
    """Cross-check citations and reference entries (numeric styles only)."""
    body, refs = split_body_references(text)
    style, entries = parse_entries(refs)
    if not refs.strip():
        return {"status": "no_references", "style": style, "entries": [],
                "uncited": [], "missing": [], "cited_count": 0}
    if style != "numeric":
        return {"status": "unsupported_style", "style": style, "entries": [],
                "uncited": [], "missing": [], "cited_count": 0}
    listed = {e["n"] for e in entries}
    cited = cited_numbers(body)
    uncited = sorted(listed - cited)
    # Numbers far beyond the list ("[64]", "[128]" — array sizes, bit widths)
    # are not citations; report only plausible gaps / slightly-too-high numbers.
    max_listed = max(listed) if listed else 0
    missing = sorted(n for n in cited - listed if n <= max_listed + 3)
    return {
        "status": "ok",
        "style": style,
        "entries": entries,
        "cited_count": len(cited),
        "uncited": uncited,          # in the list, never cited in the text
        "missing": missing,          # cited in the text, not in the list
    }


# ── Online verification ──────────────────────────────────────────────────────

_UA = {"User-Agent": "ProgramChairCopilot/1.0 (reference checker)"}
_NOT_CHECKABLE_RE = re.compile(
    r'(datasheet|data sheet|user guide|manual|white ?paper|accessed|retrieved|online\]|\[online|'
    r'available( at)?:|github\.com|standard\b|std\.|iso[ /]|iec |rfc ?\d|patent|technical report|tech\. rep)',
    re.IGNORECASE,
)


_ALWAYS_UNCHECKABLE_RE = re.compile(
    r'(datasheet|data sheet|github|repository|user guide|reference manual|product brief|website|homepage)',
    re.IGNORECASE)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9 ]+', ' ', s).strip()


def guess_title(entry: str) -> str:
    """IEEE puts the title in quotes; otherwise take the longest sentence-like chunk."""
    m = re.search(r'[“"]([^”"]{12,300})[”"]', entry)
    if m:
        return m.group(1).strip(" ,.")
    chunks = [c.strip() for c in re.split(r'\.\s+', entry) if c.strip()]
    chunks = [c for c in chunks if len(c.split()) >= 4 and not re.search(r'\b(19|20)\d{2}\b.*\bpp?\.', c)]
    return max(chunks, key=len) if chunks else entry[:200]


def _title_matches(candidate: str, title: str, entry: str) -> int:
    c, t, e = _fold(candidate), _fold(title), _fold(entry)
    if len(c) < 12:
        return 0
    # also compare with spaces removed: extraction sometimes drops/inserts spaces
    cn, tn, en = c.replace(" ", ""), t.replace(" ", ""), e.replace(" ", "")
    return int(max(fuzz.ratio(c, t), fuzz.ratio(cn, tn),
                   fuzz.partial_ratio(cn, en) if len(cn) <= len(en) else 0))


class _Throttled(Exception):
    pass


async def _get_json(client, url: str, params: dict, attempts: int = 3):
    """GET with retry/backoff on rate limits (429), throttling (202) and
    transient errors. The public APIs throttle anonymous bursts."""
    delay = 1.5
    for i in range(attempts):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (202, 429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After")
                wait = min(float(ra), 6.0) if ra and ra.replace(".", "", 1).isdigit() else delay
            else:
                r.raise_for_status()
                return r.json()
        except (httpx.TimeoutException, httpx.TransportError):
            wait = delay
        if i < attempts - 1:
            await asyncio.sleep(wait)
            delay *= 2
    raise _Throttled(url)


async def _lookup_crossref(client, entry: str) -> list[dict]:
    data = await _get_json(client, "https://api.crossref.org/works",
                           {"query.bibliographic": entry[:300], "rows": 3,
                            "select": "title,DOI,issued,container-title"})
    out = []
    for it in data.get("message", {}).get("items", []):
        title = (it.get("title") or [""])[0]
        year = ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        out.append({"title": title, "doi": it.get("DOI"), "year": year,
                    "venue": (it.get("container-title") or [""])[0], "source": "Crossref"})
    return out


async def _lookup_openalex(client, title: str, api_key: str) -> list[dict]:
    # OpenAlex requires a (free) API key; anonymous use shares a small daily
    # budget per network IP, which a university network exhausts quickly.
    data = await _get_json(client, "https://api.openalex.org/works",
                           {"search": title[:250], "per-page": 3, "api_key": api_key,
                            "select": "title,doi,publication_year,primary_location"})
    out = []
    for it in data.get("results", []):
        loc = it.get("primary_location") or {}
        src = (loc.get("source") or {}) if isinstance(loc, dict) else {}
        out.append({"title": it.get("title") or "", "doi": (it.get("doi") or "").replace("https://doi.org/", ""),
                    "year": it.get("publication_year"), "venue": src.get("display_name") or "",
                    "source": "OpenAlex"})
    return out


async def _verify_one(client, sem, entry: dict, openalex_key: str = "") -> dict:
    text = entry["text"]
    title = guess_title(text)
    res = {"n": entry["n"], "text": text, "guessed_title": title}
    if (_ALWAYS_UNCHECKABLE_RE.search(title) or re.search(r'github\.com|\bgithub\b', text, re.I)
            or (_NOT_CHECKABLE_RE.search(text) and not re.search(r'[“"]', text))):
        return {**res, "status": "not_checkable", "note": "Web page, datasheet, standard or report — not indexed"}
    best, best_score, errors = None, 0, 0
    async with sem:
        sources = [(_lookup_crossref, text)]
        if openalex_key:
            sources.append((lambda c, a: _lookup_openalex(c, a, openalex_key), title))
        for fn, arg in sources:
            try:
                cands = await fn(client, arg)
            except Exception:
                errors += 1
                continue
            for c in cands:
                s = _title_matches(c["title"], title, text)
                if s > best_score:
                    best, best_score = c, s
            if best_score >= 90:
                break
    if best_score >= 90:
        status = "verified"
    elif best_score >= 75:
        status = "likely"
    elif errors:
        # Don't call it "not found" unless every database actually answered.
        return {**res, "status": "error", "score": best_score,
                "note": "Lookup service busy or unreachable - retry later"}
    else:
        status = "not_found"
    out = {**res, "status": status, "score": best_score,
           "match": best if best_score >= 75 else None}
    if status == "not_found" and re.search(r'arxiv|preprint', text, re.I):
        out["note"] = "Preprint: arXiv papers are often missing from Crossref (add an OpenAlex key)"
    return out


async def verify_references(entries: list[dict], concurrency: int = 3,
                            overall_timeout: float = 180.0, openalex_key: str = "") -> list[dict]:
    """Look up each entry; keeps partial results if the overall cap is reached."""
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=15.0, headers=_UA, follow_redirects=True) as client:
        tasks = [asyncio.create_task(_verify_one(client, sem, e, openalex_key)) for e in entries]
        done, pending = await asyncio.wait(tasks, timeout=overall_timeout)
        for t in pending:
            t.cancel()
    out = []
    for e, t in zip(entries, tasks):
        if t in done and not t.cancelled() and t.exception() is None:
            out.append(t.result())
        else:
            out.append({"n": e["n"], "text": e["text"], "status": "error", "note": "Timed out"})
    return out
