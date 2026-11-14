"""Extract once: one pass over a PDF builds a document model that every check reads.

The model is a plain JSON-serialisable dict so it can be cached in SQLite by
file hash; a re-run of any check on an unchanged file never re-opens the PDF.

Model (top level)
  version, sha256, filename, n_pages, encrypted, error
  metadata        {title, author, subject, keywords, creator, producer}
  fonts           {unembedded: [...], total: int}
  body_size       dominant font size of the running text
  pages           see _page_model
  page_texts      reading-order text per page
  full_text       page_texts joined with "\n"
  ref_page        1-based page where the references heading is (None if not found)
  title_guess     largest-font text near the top of page 1
  abstract, keywords_text
  sections        [{title, page, number}]
  captions        [{kind: figure|table, label, page, text}]
  citations       references.analyse_citations() output (entries, uncited, missing)
"""

import io
import re
import statistics
from collections import Counter

DOCMODEL_VERSION = 4

_ZERO_WIDTH = re.compile('[​-‏⁠-⁤﻿­]')
_TAG_CHARS = re.compile('[\U000e0000-\U000e007f]')


def _r(x, nd=1):
    try:
        return round(float(x), nd)
    except Exception:
        return 0.0


def _luminance(color):
    """0 = black .. 1 = white for a pdfplumber colour tuple, None if unknown."""
    if color is None:
        return None
    if isinstance(color, (int, float)):
        color = (color,)
    try:
        c = [float(v) for v in color]
    except Exception:
        return None
    if len(c) == 1:
        return c[0]
    if len(c) == 3:
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    if len(c) == 4:  # CMYK
        k = c[3]
        r, g, b = [(1 - v) * (1 - k) for v in c[:3]]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    return None


def _is_bold(font: str) -> bool:
    f = (font or "").lower()
    return any(t in f for t in ("bold", "black", "heavy", "semibold", "-medi", "cmbx", "bx1", "+bx", "demi"))


def _lines_from_words(words, page_w):
    """Group words into visual lines, splitting a row where a wide gap
    separates two columns."""
    # Group on the baseline (bottom): small caps and drop caps share it, their tops differ.
    rows = []
    for w in sorted(words, key=lambda w: (w["bottom"], w["x0"])):
        if rows and abs(rows[-1][0]["bottom"] - w["bottom"]) <= 2.0:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        cur = [row[0]]
        for w in row[1:]:
            size = float(w.get("size") or 10)
            if w["x0"] - cur[-1]["x1"] > max(7.0, 1.0 * size):  # IEEE gutter ≈ 12–14 pt; word gaps < 0.6 em
                lines.append(cur); cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
    out = []
    for ln in lines:
        sizes = [float(w.get("size") or 0) for w in ln]
        fonts = Counter(str(w.get("fontname") or "") for w in ln)
        font = fonts.most_common(1)[0][0] if fonts else ""
        out.append({
            "t": " ".join(w["text"] for w in ln),
            "x0": _r(min(w["x0"] for w in ln)), "x1": _r(max(w["x1"] for w in ln)),
            "top": _r(min(w["top"] for w in ln)), "bottom": _r(max(w["bottom"] for w in ln)),
            "size": _r(statistics.median(sizes) if sizes else 0),
            "font": font, "bold": _is_bold(font),
        })
    out.sort(key=lambda l: (l["x0"] > page_w * 0.5 and l["x1"] > page_w * 0.55, l["top"], l["x0"]))
    return out


def _group_chars(chars):
    """Join characters into short strings (same line, adjacent)."""
    groups = []
    for ch in sorted(chars, key=lambda c: (round(c["top"]), c["x0"])):
        if groups:
            g = groups[-1]
            size = float(ch.get("size") or 4)
            gap = ch["x0"] - g["x1"]
            if abs(g["top"] - ch["top"]) < 2 and gap < max(6.0, size * 1.5):
                g["text"] += (" " if gap > size * 0.2 else "") + ch.get("text", "")
                g["x1"] = ch["x1"]; g["bottom"] = max(g["bottom"], ch["bottom"])
                g["min_size"] = min(g["min_size"], float(ch.get("size") or 0))
                continue
        groups.append({"text": ch.get("text", ""), "x0": ch["x0"], "x1": ch["x1"], "top": ch["top"],
                       "bottom": ch["bottom"], "min_size": float(ch.get("size") or 0)})
    return groups


def _covered_by_fill(ch, fills):
    cx = (ch["x0"] + ch["x1"]) / 2; cy = (ch["top"] + ch["bottom"]) / 2
    for f in fills:
        if f[0] - 1 <= cx <= f[2] + 1 and f[1] - 1 <= cy <= f[3] + 1:
            return True
    return False


def _hidden_candidates(page, w, h):
    """Characters a reader cannot see: white on a white page, tiny, or off-page."""
    out = []
    chars = page.chars
    if not chars:
        return out
    # Non-white fills (dark boxes, coloured cells) and images: white text on top of these is visible.
    fills = []
    for obj in list(page.rects) + list(page.curves):
        if obj.get("fill"):
            lum = _luminance(obj.get("non_stroking_color"))
            if lum is None or lum < 0.9:
                fills.append((obj["x0"], obj["top"], obj["x1"], obj["bottom"]))
    for im in page.images:
        fills.append((im["x0"], im["top"], im["x1"], im["bottom"]))

    white, tiny, offpage = [], [], []
    for ch in chars:
        t = ch.get("text", "")
        if not t.strip():
            continue
        if ch["x1"] < 0 or ch["x0"] > w or ch["bottom"] < 0 or ch["top"] > h:
            offpage.append(ch); continue
        size = float(ch.get("size") or 0)
        if 0 < size < 3.0:
            tiny.append(ch)
        lum = _luminance(ch.get("non_stroking_color"))
        if lum is not None and lum > 0.95 and not _covered_by_fill(ch, fills):
            white.append(ch)
    for reason, chs in (("white", white), ("tiny", tiny), ("offpage", offpage)):
        for g in _group_chars(chs):
            if len(g["text"].strip()) >= 3:
                out.append({"reason": reason, "text": g["text"][:500], "size": _r(g["min_size"]),
                            "bbox": [_r(g["x0"]), _r(g["top"]), _r(g["x1"]), _r(g["bottom"])]})
    return out[:50]


def _page_model(page, idx, reading_text):
    w, h = float(page.width), float(page.height)
    pm = {"n": idx + 1, "width": _r(w), "height": _r(h), "rotation": int(page.rotation or 0),
          "n_chars": 0, "image_area": 0.0, "n_images": 0, "lines": [], "annots": [], "links": [],
          "hidden": [], "cid": 0, "fffd": 0, "zero_width": 0, "tag_chars": 0, "error": None}
    try:
        chars = page.chars
        pm["n_chars"] = len(chars)
        try:  # font-size-relative gap: tightly kerned PDFs otherwise lose their spaces
            words = page.extract_words(x_tolerance_ratio=0.15, extra_attrs=["size", "fontname"])
        except TypeError:
            words = page.extract_words(extra_attrs=["size", "fontname"])
        pm["lines"] = _lines_from_words(words, w)
        area = 0.0
        for im in page.images:
            iw = max(0.0, min(im["x1"], w) - max(im["x0"], 0)); ih = max(0.0, min(im["bottom"], h) - max(im["top"], 0))
            area += iw * ih
        pm["n_images"] = len(page.images)
        pm["image_area"] = _r(min(1.0, area / (w * h)) if w and h else 0, 3)
        for a in page.annots or []:
            data = a.get("data") or {}
            sub = data.get("Subtype")
            sub = getattr(sub, "name", None) or str(sub or "")
            sub = sub.lstrip("/")
            if sub in ("Link", "Widget", ""):
                continue
            contents = a.get("contents") or data.get("Contents") or ""
            if isinstance(contents, bytes):
                contents = contents.decode("utf-8", "ignore")
            pm["annots"].append({"subtype": sub, "contents": str(contents)[:300]})
        for hl in page.hyperlinks or []:
            uri = hl.get("uri")
            if isinstance(uri, bytes):
                uri = uri.decode("utf-8", "ignore")
            if uri:
                pm["links"].append(str(uri)[:300])
        pm["hidden"] = _hidden_candidates(page, w, h)
    except Exception as e:  # a damaged page must not kill the whole extraction
        pm["error"] = f"{type(e).__name__}: {e}"[:200]
    t = reading_text or ""
    pm["cid"] = t.count("(cid:")
    pm["fffd"] = t.count("�")
    pm["zero_width"] = len(_ZERO_WIDTH.findall(t))
    pm["tag_chars"] = len(_TAG_CHARS.findall(t))
    return pm


# ── Structure: title, abstract, sections, captions ────────────────────────────

_SECTION_RE = re.compile(
    r'^(?P<num>(?:[IVX]{1,5}|\d{1,2}(?:\.\d{1,2})?|[A-H])\.?)\s+(?P<title>[A-Z][A-Za-z0-9 ,:&/\-–]{2,70})$')
_UNNUMBERED = re.compile(
    r'^(abstract|introduction|related work|background|conclusions?|concluding remarks|summary|'
    r'acknowledg(?:e)?ments?|references|bibliography|appendix|discussion|evaluation|results|'
    r'experimental results|future work|limitations|ethics statement|funding)\.?$', re.I)
_CAPTION_RE = re.compile(
    r'^(?P<kind>fig\.?|figure|table|tab\.)\s*(?P<label>[IVX]{1,6}|\d{1,3}|[A-Z]\.\d{1,2})\s*[.:|—–-]', re.I)


def _unsmallcap(t):
    """'I NTRODUCTION' / 'H OTSPOT -A WARE' (small caps split by extraction) -> 'INTRODUCTION' / 'HOTSPOT-AWARE'."""
    t = re.sub(r'\b([A-Z]) (?=[A-Z]{2,}\b)', r'\1', t)
    return re.sub(r' -([A-Z])', r'-\1', t)


def _structure(pages, body_size):
    sections, captions = [], []
    for p in pages:
        for ln in p["lines"]:
            t = _unsmallcap(ln["t"].strip())
            if not t:
                continue
            m = _CAPTION_RE.match(t)
            if m:
                kind = "figure" if m.group("kind").lower().startswith("fig") else "table"
                captions.append({"kind": kind, "label": m.group("label").upper(), "page": p["n"], "text": t[:200]})
                continue
            if len(t) > 90:
                continue
            big_or_bold = ln["bold"] or (body_size and ln["size"] >= body_size + 0.4) or t.isupper()
            m = _SECTION_RE.match(t)
            if m and big_or_bold and not t.endswith("."):
                sections.append({"number": m.group("num").rstrip("."), "title": m.group("title").strip(), "page": p["n"]})
            elif _UNNUMBERED.match(t) and big_or_bold:
                sections.append({"number": "", "title": t.rstrip("."), "page": p["n"]})
    return sections, captions


def _title_guess(pages):
    if not pages:
        return ""
    p = pages[0]
    top = [l for l in p["lines"] if l["top"] < p["height"] * 0.45 and len(l["t"]) > 3]
    if not top:
        return ""
    mx = max(l["size"] for l in top)
    tl = sorted([l for l in top if l["size"] >= mx - 0.5], key=lambda l: l["top"])
    return " ".join(l["t"] for l in tl)[:400]


_ABSTRACT_RE = re.compile(
    r'(?is)\babstract\b\s*[—–:.\-]*\s*(?P<a>.+?)(?=\n\s*(?:index terms|keywords|key words|ccs concepts|'
    r'(?:I|1)\.?\s+introduction|introduction\b)|$)')
_KEYWORDS_RE = re.compile(r'(?is)\b(index terms|keywords|key words)\b\s*[—–:.\-]*\s*(?P<k>.{3,400}?)(?:\n\s*\n|\n\s*(?:I|1)\.?\s+introduction|$)')


def _abstract_keywords(page_texts):
    first = "\n".join(page_texts[:2])[:12000]
    a = _ABSTRACT_RE.search(first)
    abstract = " ".join(a.group("a").split())[:4000] if a else ""
    k = _KEYWORDS_RE.search(first)
    kw = " ".join(k.group("k").split()) if k else ""
    return abstract, kw


# ── Entry point ───────────────────────────────────────────────────────────────

def build(pdf_bytes: bytes, sha256: str, filename: str = "") -> dict:
    import pdfplumber
    import pdf_checker
    import references as references_mod

    model = {"version": DOCMODEL_VERSION, "sha256": sha256, "filename": filename, "n_pages": 0,
             "encrypted": False, "error": None, "metadata": {}, "fonts": {"unembedded": [], "total": 0},
             "body_size": 0.0, "pages": [], "page_texts": [], "full_text": "", "ref_page": None,
             "title_guess": "", "abstract": "", "keywords_text": "", "sections": [], "captions": [],
             "citations": {}}
    if not pdf_bytes or not pdf_bytes.lstrip()[:5].startswith(b"%PDF"):
        model["error"] = "Not a PDF file."
        return model
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception as e:
        msg = str(e).lower()
        model["encrypted"] = "password" in msg or "encrypt" in msg
        model["error"] = "The PDF is encrypted." if model["encrypted"] else f"The PDF could not be opened ({type(e).__name__})."
        return model
    with pdf:
        md = pdf.metadata or {}
        def _m(k):
            v = md.get(k) or ""
            if isinstance(v, bytes):
                v = v.decode("utf-8", "ignore")
            return str(v)[:500]
        model["metadata"] = {k.lower(): _m(k) for k in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer")}
        model["n_pages"] = len(pdf.pages)
        texts = []
        for i, page in enumerate(pdf.pages):
            try:
                t = references_mod._page_reading_text(page)
            except Exception:
                t = ""
            texts.append(t)
            model["pages"].append(_page_model(page, i, t))
        model["page_texts"] = texts
        model["full_text"] = "\n".join(texts)
        try:
            idx, _ = pdf_checker._locate_references(pdf, texts)
            model["ref_page"] = idx + 1 if idx >= 0 else None
        except Exception:
            pass
        try:
            fr = pdf_checker._check_font_embedding(pdf)
            model["fonts"] = {"unembedded": [] if fr.passed else list(fr.issues)[:20], "total": 0, "summary": fr.value}
        except Exception:
            pass
    sizes = Counter()
    for p in model["pages"]:
        for ln in p["lines"]:
            sizes[ln["size"]] += len(ln["t"])
    model["body_size"] = sizes.most_common(1)[0][0] if sizes else 0.0
    model["title_guess"] = _title_guess(model["pages"])
    model["abstract"], model["keywords_text"] = _abstract_keywords(texts)
    model["sections"], model["captions"] = _structure(model["pages"], model["body_size"])
    try:
        model["citations"] = references_mod.analyse_citations(model["full_text"])
    except Exception:
        model["citations"] = {}
    return model


# ── Helpers used by the checks ────────────────────────────────────────────────

def body_text(doc) -> str:
    """Text before the references heading (falls back to everything)."""
    import references as references_mod
    body, _ = references_mod.split_body_references(doc.get("full_text", ""))
    return body


def find_page(doc, needle: str):
    """1-based page where `needle` first occurs (whitespace-insensitive), or None."""
    if not needle:
        return None
    n = " ".join(needle.split())[:60].lower()
    for i, t in enumerate(doc.get("page_texts", [])):
        if n in " ".join(t.split()).lower():
            return i + 1
    return None


def snippet(text: str, start: int, end: int, pad: int = 70) -> str:
    s = max(0, start - pad); e = min(len(text), end + pad)
    return ("..." if s > 0 else "") + " ".join(text[s:e].split()) + ("..." if e < len(text) else "")


def iter_matches(doc, regex, text=None, limit=20):
    """Yield (page, excerpt, match) for regex hits, page by page."""
    count = 0
    pages = doc.get("page_texts", []) if text is None else [text]
    for i, t in enumerate(pages):
        for m in regex.finditer(t):
            yield (i + 1 if text is None else find_page(doc, m.group(0))), snippet(t, m.start(), m.end()), m
            count += 1
            if count >= limit:
                return
