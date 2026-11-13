"""
pdf_checker.py — deterministic PDF compliance checks using pdfplumber.
No LLM calls. Returns structured results for each check.
"""

import re
import pdfplumber
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CheckResult:
    passed: bool
    value: str = ""
    issues: list[str] = field(default_factory=list)


@dataclass
class PDFCheckReport:
    filename: str
    page_count: CheckResult
    font_embedding: CheckResult
    blind_compliance: CheckResult
    author_info_present: CheckResult
    copyright_notice: CheckResult
    pdf_express: CheckResult
    text_extraction: CheckResult
    column_layout: CheckResult = field(default_factory=lambda: CheckResult(passed=True))
    references: CheckResult = field(default_factory=lambda: CheckResult(passed=True))
    citations: CheckResult = field(default_factory=lambda: CheckResult(passed=True, value="Not checked"))
    reference_entries: list = field(default_factory=list)   # [{"n", "text"}] for online verification
    reading_text: str = ""       # column-aware full text (cached for cheap LLM screening)
    raw_pages: int = 0
    body_pages: int = 0          # pages before the references heading
    reference_pages: int = 0     # references + anything after (appendix)
    raw_text_sample: str = ""
    error: Optional[str] = None


# ── helpers ───────────────────────────────────────────────────────────────────

# Reliable blind-compliance signals — these are specific enough to not false-positive
_EMAIL_RE    = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_ORCID_RE    = re.compile(r'orcid\.org|ORCID|0000-\d{4}-\d{4}-\d{3}[\dX]', re.IGNORECASE)

# Affiliation keywords — only meaningful in the author header area (top of page 1)
_AFF_RE = re.compile(
    r'\b(?:'
    r'[Uu]niversity|[Uu]niversit[àáâãä]|[Uu]niversidad|[Uu]niversit[eé]'
    r'|[Ii]nstitut(?:e|o|ion)?'
    r'|[Dd]epartment|[Dd]ept\.'
    r'|[Ll]aborator(?:y|ies|io)'
    r'|[Ff]acult(?:y|ad)'
    r'|[Ss]chool\s+of'
    r'|[Cc]ollege\s+of'
    r'|[Pp]olitecnico'
    r'|[Tt]echnische\s+[Uu]niversit'
    r'|[Gg]raduate\s+[Ss]chool'
    r')\b'
)

# Name-like pattern — used ONLY in the author header zone, not full page text
# Requires: First Last format where both parts ≥ 3 chars, not all-caps (avoids acronyms)
_NAME_RE = re.compile(r'\b([A-Z][a-z]{2,}(?:\s[A-Z]\.)?)\s+([A-Z][a-z]{2,})\b')

# Words that look like names but are actually common technical/section terms
# Any two-word phrase where either word is in this set is NOT flagged as a name
_NAME_STOPWORDS_SINGLE = {
    # Section / structural words
    "abstract", "introduction", "conclusion", "conclusions", "references",
    "acknowledgement", "acknowledgements", "appendix", "bibliography",
    "related", "proposed", "experimental", "results", "discussion",
    "evaluation", "analysis", "overview", "background", "motivation",
    "contribution", "contributions", "summary", "future", "previous",
    "section", "figure", "table", "algorithm", "equation", "theorem",
    "definition", "lemma", "proof", "corollary", "remark",
    # Technical / domain words that start with capital in titles
    "deep", "neural", "machine", "natural", "computer", "signal",
    "image", "video", "speech", "language", "vision", "learning",
    "network", "model", "system", "method", "approach", "framework",
    "architecture", "algorithm", "dataset", "benchmark", "baseline",
    "training", "testing", "inference", "detection", "recognition",
    "classification", "segmentation", "generation", "optimization",
    "performance", "accuracy", "precision", "recall", "efficiency",
    "robust", "scalable", "lightweight", "real", "large", "small",
    "high", "low", "fast", "slow", "novel", "new", "improved",
    "enhanced", "advanced", "unified", "joint", "multi", "cross",
    "semi", "self", "end", "state", "art", "based", "driven",
    # Application / domain words
    "temperature", "pressure", "voltage", "current", "power", "energy",
    "frequency", "sensor", "actuator", "control", "wireless", "optical",
    "thermal", "mechanical", "electrical", "digital", "analog", "mixed",
    "validated", "verified", "certified", "approved", "tested",
    "applications", "application", "environments", "environment",
    "conditions", "condition", "scenarios", "scenario", "cases", "case",
    "challenges", "challenge", "solutions", "solution", "problems",
    "problem", "issues", "issue", "techniques", "technique",
    # Common paper title words
    "towards", "using", "based", "driven", "enabled", "assisted",
    "aware", "efficient", "effective", "accurate", "reliable",
    "scalable", "flexible", "adaptive", "dynamic", "static",
    # Publisher / venue words
    "international", "conference", "journal", "workshop", "symposium",
    "transactions", "proceedings", "letters", "communications",
    # Misc false positives seen in practice
    "ground", "truth", "state", "prior", "work", "paper", "study",
    "survey", "review", "report", "note", "letter", "brief",
    # Template placeholders ("Author One", "Name Surname", "Given Name", "Unknown Authors")
    "author", "authors", "name", "surname", "given", "family", "unknown",
    "first", "last", "middle", "one", "two", "three", "four", "five", "six",
    "anonymous", "affiliation", "institution", "organization", "department",
    "chair", "institute", "systems", "hardware", "software", "electronic",
    "embedded", "grenoble", "alpes",
}

def _is_likely_name(word1: str, word2: str) -> bool:
    """Return True only if this two-word phrase looks like a real person's name."""
    w1 = word1.lower()
    w2 = word2.lower()
    # Reject if either word is a known non-name word
    if w1 in _NAME_STOPWORDS_SINGLE or w2 in _NAME_STOPWORDS_SINGLE:
        return False
    # Reject if either word ends in common non-name suffixes
    non_name_suffixes = (
        "tion", "sion", "ment", "ness", "ity", "ance", "ence",
        "ling", "ing", "ated", "ized", "ised", "ous", "ive",
        "ful", "less", "ward", "wise", "able", "ible",
    )
    if any(w1.endswith(s) for s in non_name_suffixes):
        return False
    if any(w2.endswith(s) for s in non_name_suffixes):
        return False
    # Reject very long words (names rarely exceed 12 chars)
    if len(word1) > 12 or len(word2) > 12:
        return False
    return True


def _extract_author_block(page) -> str:
    """
    Extract text from the author header zone of page 1.
    Uses word coordinates to isolate top 30% of page (title + author area).
    Falls back to first 800 chars if coordinate extraction fails.
    """
    try:
        words = page.extract_words(keep_blank_chars=False)
        if not words:
            return (page.extract_text() or "")[:800]
        page_height = float(page.height)
        cutoff = page_height * 0.30
        author_words = [w["text"] for w in words if float(w.get("top", 0)) <= cutoff]
        return " ".join(author_words)
    except Exception:
        return (page.extract_text() or "")[:800]


def _page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def _extract_text(pdf, max_pages: int = 3) -> str:
    """Extract text from first N pages for fast checks."""
    return "\n".join(_page_text(p) for p in pdf.pages[:max_pages])


def _extract_all_text(pdf) -> str:
    return "\n".join(_page_text(p) for p in pdf.pages)


def _group_lines(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    """Group words into visual lines by their 'top' coordinate."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (float(w.get("top", 0)), float(w.get("x0", 0)))):
        top = float(w.get("top", 0))
        if lines and abs(float(lines[-1][0].get("top", 0)) - top) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: float(w.get("x0", 0)))
    return lines


# Reference-section heading: a whole line, optionally numbered
# ("References", "REFERENCES", "R E F E R E N C E S", "VII. REFERENCES",
#  "7 References", "Bibliography", "Literature Cited").
_REF_HEAD_WORD = (
    r'(?:R\s?E\s?F\s?E\s?R\s?E\s?N\s?C\s?E\s?S?|References?|Bibliography|BIBLIOGRAPHY'
    r'|Literature\s+Cited|LITERATURE\s+CITED|Works\s+Cited|WORKS\s+CITED)'
)
_REF_NUM_PREFIX = r'(?:(?:[IVXLC]{1,6}|\d{1,2}|[A-Z])\s*[.):]?\s+)?'
_REF_HEADING_RE = re.compile(
    r'(?m)^[ \t]*' + _REF_NUM_PREFIX + _REF_HEAD_WORD + r'\b[ \t]*:?[ \t]*$'
)
_REF_HEAD_TOKEN_RE = re.compile(r'^' + _REF_HEAD_WORD + r':?$')
_REF_PREFIX_TOKEN_RE = re.compile(r'^(?:[IVXLC]{1,6}|\d{1,2}|[A-Z])[.):]?$')


def _find_ref_heading_on_page(page, text: str) -> Optional[float]:
    """Return the 'top' (y) of a references heading on this page, or None.

    1. Whole-line regex on the extracted text (single-column / clean extraction).
    2. Word-level fallback for two-column pages, where extract_text() glues
       the heading to text of the other column: a heading word with no other
       word close to it on the same visual line (inside its column).
    """
    try:
        words = page.extract_words() or []
    except Exception:
        words = []
    width = float(getattr(page, "width", 0) or 0) or 612.0

    def _top_of(word_texts: list[str]) -> Optional[float]:
        for w in words:
            if _REF_HEAD_TOKEN_RE.match(w["text"]) and w["text"].strip(":") in word_texts:
                return float(w["top"])
        return None

    m = _REF_HEADING_RE.search(text or "")
    if m:
        heading_word = m.group(0).strip().split()[-1].strip(":")
        top = _top_of([heading_word])
        # position unknown → assume mid-page (page still counts as body)
        return top if top is not None else float(getattr(page, "height", 792) or 792) * 0.5

    if not words:
        return None
    for line in _group_lines(words):
        for idx, w in enumerate(line):
            if not _REF_HEAD_TOKEN_RE.match(w["text"]):
                continue
            # optional numbering token directly before it
            left = line[:idx]
            if left and _REF_PREFIX_TOKEN_RE.match(left[-1]["text"]) and \
                    float(w["x0"]) - float(left[-1]["x1"]) < width * 0.03:
                left = left[:-1]
            right = line[idx + 1:]
            near_left = [x for x in left if float(w["x0"]) - float(x["x1"]) < width * 0.12]
            near_right = [x for x in right if float(x["x0"]) - float(w["x1"]) < width * 0.12]
            if not near_left and not near_right:
                return float(w["top"])
    return None


def _locate_references(pdf, page_texts: list[str]) -> tuple[int, Optional[float]]:
    """(page index, heading top) of the references heading, or (-1, None).
    Searches the last 50% of pages first, then the rest."""
    total = len(pdf.pages)
    search_from = max(0, int(total * 0.50))
    for rng in (range(search_from, total), range(0, search_from)):
        for i in rng:
            try:
                top = _find_ref_heading_on_page(pdf.pages[i], page_texts[i])
            except Exception:
                top = None
            if top is not None:
                return i, top
    return -1, None


def _detect_references(pdf, page_texts: Optional[list[str]] = None) -> tuple[bool, int, list[str]]:
    """
    Detect whether a references section exists and count entries.

    Strategy:
    - Find a references heading (whole line / isolated word), last 50% first
    - Count by finding max reference number in [N] notation (most reliable)
    - Fall back to counting numbered list entries (1. 2. 3.)
    - Fall back to counting author-year blocks as last resort

    Returns: (found: bool, count: int, issues: list[str])
    """
    if page_texts is None:
        page_texts = [_page_text(p) for p in pdf.pages]
    ref_page_found, _ = _locate_references(pdf, page_texts)
    if ref_page_found == -1:
        return False, 0, ["No references section found"]
    ref_section_text = "\n".join(page_texts[ref_page_found:])

    count = 0
    issues = []

    # ── Strategy A: bracketed numbers [N] anywhere in text ───────────────────
    bracketed_nums = re.findall(r'\[(\d+)\]', ref_section_text)
    if bracketed_nums:
        max_ref = max(int(n) for n in bracketed_nums)
        if 1 <= max_ref <= 500:
            count = max_ref

    # ── Strategy B: numbered list "1." or "1)" at line start ─────────────────
    if count == 0:
        numbered = re.findall(r'(?m)^\s*(\d{1,3})[.)]\s+\S', ref_section_text)
        if numbered:
            count = max(int(n) for n in numbered)

    # ── Strategy C: author-year entries "Lastname, F." at line start ─────────
    if count == 0:
        author_year = re.findall(
            r'(?m)^([A-Z][a-zA-Zàáâãäåæçèéêëìíîïðñòóôõöùúûü\-]{2,},\s+[A-Z])',
            ref_section_text
        )
        if author_year:
            count = len(author_year)

    if count == 0:
        issues.append("References section found but could not count entries — format may be non-standard")

    return True, count, issues


def _detect_column_layout(page) -> str:
    """
    Detect single vs two-column layout.

    Signal 1 — per-line centre analysis (x-distribution of words):
      Words are grouped into visual lines. A line is
        * "spanning" if a word straddles the page centre or the line crosses
          the centre with only a normal word gap there,
        * "split" if it has words left of the centre and words right of it
          separated by a gutter-sized gap (two columns sharing a baseline),
        * "half" if all its words are on one side of the centre.
      Two-column pages have almost no spanning lines and a substantial share
      of lines with content starting right of the centre.

    Signal 2 — character-density gutter (fallback):
      A near-empty vertical band in the centre zone.

    Returns: "single", "two-column", or "unknown"
    """
    try:
        page_width  = float(page.width)
        page_height = float(page.height)
        top_cutoff  = page_height * 0.12
        bottom_cutoff = page_height * 0.94
        centre = page_width * 0.5
        gutter_min = page_width * 0.015

        words = page.extract_words()
        body  = [w for w in words
                 if top_cutoff < float(w.get("top", 0)) < bottom_cutoff]
        if len(body) < 20:
            return "unknown"

        spanning = split = left_only = right_only = 0
        for line in _group_lines(body):
            if any(float(w["x0"]) < centre < float(w["x1"]) for w in line):
                spanning += 1
                continue
            left = [w for w in line if float(w["x1"]) <= centre]
            right = [w for w in line if float(w["x0"]) >= centre]
            if left and right:
                gap = min(float(w["x0"]) for w in right) - max(float(w["x1"]) for w in left)
                if gap >= gutter_min:
                    split += 1
                else:
                    spanning += 1
            elif left:
                left_only += 1
            elif right:
                right_only += 1

        total = spanning + split + left_only + right_only
        if total >= 8:
            span_ratio = spanning / total
            right_ratio = (split + right_only) / total
            left_ratio = (split + left_only) / total
            if span_ratio <= 0.25 and right_ratio >= 0.2 and left_ratio >= 0.2:
                return "two-column"
            if span_ratio >= 0.5:
                return "single"

        # ── Signal 2: character-density gutter ───────────────────────────────
        chars      = page.chars
        body_chars = [c for c in chars if top_cutoff < float(c.get("top", 0)) < bottom_cutoff]
        if body_chars:
            N    = 40
            bins = [0] * N
            for c in body_chars:
                cx = (float(c["x0"]) + float(c["x1"])) / 2
                b  = min(max(int((cx / page_width) * N), 0), N - 1)
                bins[b] += 1
            zone         = bins[16:24]
            surround_avg = (sum(bins[8:14]) + sum(bins[26:32])) / 12
            gutter_ratio = min(zone) / surround_avg if surround_avg and zone else 1.0
            if gutter_ratio < 0.15:
                return "two-column"

        return "single"

    except Exception:
        return "unknown"


# ── Font embedding (font descriptors) ─────────────────────────────────────────

def _resolve(obj, depth: int = 0):
    try:
        from pdfminer.pdftypes import resolve1
        return resolve1(obj)
    except Exception:
        return obj


def _name_str(v) -> str:
    v = _resolve(v)
    if v is None:
        return ""
    name = getattr(v, "name", None)
    if name is not None:
        return name.decode("latin-1") if isinstance(name, bytes) else str(name)
    if isinstance(v, bytes):
        return v.decode("latin-1", errors="ignore")
    return str(v).lstrip("/")


def _font_embedded_status(font) -> Optional[bool]:
    """True if the font programme is embedded, False if definitely not,
    None if undeterminable."""
    font = _resolve(font)
    if not isinstance(font, dict):
        return None
    subtype = _name_str(font.get("Subtype"))
    if subtype == "Type3":
        return True                     # glyphs defined inline in the PDF
    if subtype == "Type0":
        desc = _resolve(font.get("DescendantFonts"))
        if isinstance(desc, list) and desc:
            return _font_embedded_status(desc[0])
        return None
    fd = _resolve(font.get("FontDescriptor"))
    if not isinstance(fd, dict):
        # Simple font without a descriptor: only legal for the standard 14
        # fonts, which are by definition not embedded.
        return False if subtype in ("Type1", "TrueType", "MMType1") else None
    if any(k in fd for k in ("FontFile", "FontFile2", "FontFile3")):
        return True
    return False


def _collect_fonts(resources, out: dict, seen: set, depth: int = 0):
    resources = _resolve(resources)
    if not isinstance(resources, dict) or depth > 4:
        return
    fonts = _resolve(resources.get("Font"))
    if isinstance(fonts, dict):
        for ref in fonts.values():
            key = getattr(ref, "objid", None) or id(ref)
            if key in seen:
                continue
            seen.add(key)
            f = _resolve(ref)
            if not isinstance(f, dict):
                continue
            name = _name_str(f.get("BaseFont")) or _name_str(f.get("Name")) or "?"
            status = _font_embedded_status(f)
            # Keep the "worst" known status per name (False > None > True)
            prev = out.get(name, "unset")
            if prev == "unset" or status is False or (status is None and prev is True):
                out[name] = status
    xobjs = _resolve(resources.get("XObject"))
    if isinstance(xobjs, dict):
        for ref in xobjs.values():
            key = getattr(ref, "objid", None)
            if key is not None and ("x", key) in seen:
                continue
            if key is not None:
                seen.add(("x", key))
            xo = _resolve(ref)
            attrs = getattr(xo, "attrs", None)
            if isinstance(attrs, dict) and _name_str(attrs.get("Subtype")) == "Form":
                _collect_fonts(attrs.get("Resources"), out, seen, depth + 1)


def _check_font_embedding(pdf) -> CheckResult:
    fonts: dict[str, Optional[bool]] = {}
    seen: set = set()
    for page in pdf.pages:
        try:
            _collect_fonts(page.page_obj.resources, fonts, seen)
        except Exception:
            continue
    if not fonts:
        # Fall back to the font names pdfplumber saw on characters
        names = set()
        for page in pdf.pages:
            try:
                for ch in (page.chars or []):
                    if ch.get("fontname"):
                        names.add(ch["fontname"])
            except Exception:
                pass
        if names:
            return CheckResult(passed=True, value=f"{len(names)} font(s); could not verify embedding")
        return CheckResult(passed=True, value="No font data found (image-based PDF)")

    embedded = [n for n, s in fonts.items() if s is True]
    missing = [n for n, s in fonts.items() if s is False]
    unknown = [n for n, s in fonts.items() if s is None]
    if missing:
        return CheckResult(
            passed=False,
            value=f"{len(embedded)} embedded, {len(missing)} not embedded",
            issues=[f"Non-embedded fonts: {', '.join(sorted(missing)[:5])}"],
        )
    value = f"{len(embedded)} font(s), all embedded"
    if unknown:
        value = f"{len(embedded)} embedded, {len(unknown)} undetermined"
    return CheckResult(passed=True, value=value)


# ── Identity helpers ──────────────────────────────────────────────────────────

_ANON_MARKERS = (
    "anonymous author", "anonymous authors", "anonymous affiliation",
    "anonymous institution", "anonymous email", "anonymous submission",
    "anonymized for review", "anonymised for review", "anonymized for submission",
    "anonymised for submission", "author name", "author names",
    "author affiliation", "authors omitted", "blind review", "double-blind review",
    "name withheld", "withheld for review",
)
_SOFTWARE_WORDS = re.compile(
    r'(?i)latex|tex\b|pdftex|xetex|luatex|dvips|dvipdf|word|office|acrobat|'
    r'distiller|pdf|writer|overleaf|ghostscript|quartz|chrome|skia|cairo|'
    r'libreoffice|openoffice|microsoft|adobe|windows|mac\s?os|google|apple|'
    r'printer|pages|keynote|powerpoint|inkscape|matplotlib|elsevier|ieee|acm|springer'
)
_GENERIC_AUTHOR_META = {
    "", "anonymous", "anonymous author", "anonymous authors", "author",
    "authors", "user", "admin", "administrator", "owner", "unknown", "ieee",
    "acm", "none", "n/a", "na", "-", "default", "windows user", "microsoft office user",
}


# Template / placeholder e-mails ("name.surname@xxx.xx", "email1@example.com",
# "anonym@anonym.anonym") are not identity leaks.
_PLACEHOLDER_EMAIL_RE = re.compile(
    r'(example\.(com|org|net)|@x+\.|\bxxx|anonym|^name[._]?surname@|^first[._]?last@|'
    r'^email\d*@|^author\d*@|^someone@|^user@|@(domain|email|university|institution|affiliation)\.)',
    re.IGNORECASE,
)


def _is_placeholder_email(addr: str) -> bool:
    return bool(_PLACEHOLDER_EMAIL_RE.search(addr))


_ABSTRACT_LINE_RE = re.compile(r'^\s*(abstract|index\s+terms|keywords)\b', re.IGNORECASE)


def _author_block_lines(page, frac: float = 0.40) -> list[str]:
    """Lines between the title and the abstract on page 1 (where authors go).

    The title is taken as the lines set in the largest font in the top zone;
    the block ends at the first line starting with "Abstract"/"Index Terms".
    Restricting the "looks like a name" heuristic to this block avoids flagging
    title-case phrases from the title or abstract ("Random Forest").
    """
    try:
        words = page.extract_words(extra_attrs=["size"]) or []
    except Exception:
        return _top_zone_lines(page, frac)
    cutoff = float(page.height) * frac
    zone = [w for w in words if float(w.get("top", 0)) <= cutoff]
    if not zone:
        return []
    lines = _group_lines(zone)
    max_size = max(float(w.get("size", 0) or 0) for w in zone)
    def _lsize(ln):
        return sum(float(w.get("size", 0) or 0) for w in ln) / max(len(ln), 1)
    title_idx = [i for i, ln in enumerate(lines) if _lsize(ln) >= max_size * 0.9]
    start = (max(title_idx) + 1) if title_idx else 0
    out = []
    for ln in lines[start:]:
        text = " ".join(w["text"] for w in ln)
        if _ABSTRACT_LINE_RE.match(text):
            break
        out.append(text)
    return out


def _known_author_hits(text: str, author_names: list[str]) -> list[str]:
    """Return known author names (from the EasyChair author list) found in text."""
    import unicodedata
    def _fold(s: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                       if not unicodedata.combining(c))
    found = []
    low = _fold(text)
    for name in author_names or []:
        parts = [p for p in re.split(r'\s+', _fold(name.strip())) if p]
        if len(parts) < 2:
            continue
        first, last = re.escape(parts[0]), re.escape(parts[-1])
        # Letter boundaries (not \b) so "Santhosh1" / "Kaja*" with affiliation
        # superscripts still match; allow middle names/initials in between.
        # A single trailing letter a-h before a separator is a superscript
        # affiliation mark ("Santhosha, ..." = Santhosh + affiliation a);
        # "Liu" must not match "Li", so u and later letters are excluded.
        if re.search(rf'(?<![a-z]){first}(?![a-z])(?:\s+\S+){{0,2}}\s+{last}(?:[a-h](?=[,;*\d\n]|$))?(?![a-z])', low):
            found.append(name.strip())
    return found


def _top_zone_lines(page, frac: float = 0.30) -> list[str]:
    try:
        words = page.extract_words() or []
    except Exception:
        words = []
    cutoff = float(page.height) * frac
    zone = [w for w in words if float(w.get("top", 0)) <= cutoff]
    return [" ".join(w["text"] for w in ln) for ln in _group_lines(zone)]


def _decode_meta(v) -> str:
    v = _resolve(v)
    if isinstance(v, bytes):
        try:
            if v.startswith(b"\xfe\xff"):
                return v[2:].decode("utf-16-be", errors="ignore")
            return v.decode("utf-8")
        except Exception:
            return v.decode("latin-1", errors="ignore")
    return "" if v is None else str(v)


def _metadata_identity_hits(pdf) -> list[str]:
    hits = []
    try:
        meta = pdf.metadata or {}
    except Exception:
        meta = {}
    for key, raw in meta.items():
        val = _decode_meta(raw).strip()
        if not val:
            continue
        for m in _EMAIL_RE.finditer(val):
            hits.append(f"Email in PDF metadata ({key}): {m.group(0)}")
        if key == "Author":
            if val.strip().lower() not in _GENERIC_AUTHOR_META and "anonym" not in val.lower():
                hits.append(f"PDF metadata Author field: \"{val[:60]}\"")
        elif key == "Creator":
            if not _SOFTWARE_WORDS.search(val):
                for m in _NAME_RE.finditer(val):
                    if _is_likely_name(m.group(1), m.group(2)):
                        hits.append(f"PDF metadata Creator field looks like a name: \"{val[:60]}\"")
                        break
    return list(dict.fromkeys(hits))


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _author_on_page(name: str, page_text_norm: str) -> bool:
    """True if `name` appears on the page: surname as a whole word AND the
    first name (whole word) or its initial ("J." / "J.-P.") close before it,
    or "Surname, First/F." order. page_text_norm must be accent-stripped."""
    toks = re.findall(r"[A-Za-z][A-Za-z'\-]*", _strip_accents(name or ""))
    if not toks:
        return False
    if len(toks) == 1:
        return re.search(r'\b' + re.escape(toks[0]) + r'\b', page_text_norm, re.IGNORECASE) is not None
    first, last = toks[0], toks[-1]
    sur = re.escape(last)
    fi = re.escape(first[0])
    fn = re.escape(first)
    patterns = [
        # First [Middle/initials] Surname (within ~40 chars)
        rf'\b{fn}\b[^\n]{{0,40}}?\b{sur}\b',
        # J. Surname / J.-P. Surname / J. K. Surname
        rf'\b{fi}\.(?:\s*-?\s*[A-Z]\.)*\s*(?:[A-Z][a-z]+\s+)?{sur}\b',
        # Surname, First / Surname, J.
        rf'\b{sur},\s*(?:{fn}\b|{fi}\.)',
    ]
    return any(re.search(p, page_text_norm, re.IGNORECASE) for p in patterns)


# ── PDF eXpress stamp ─────────────────────────────────────────────────────────

# Explicit eXpress / compliance phrases only — a bare "IEEE Xplore" occurs in
# countless reference lists and must not count.
_STAMP_PATTERNS = [
    r'IEEE\s*PDF\s*e?Xpress',
    r'PDF\s*e?Xpress',
    r'Certified\s+by\s+IEEE\s*PDF',
    r'IEEE\s+Xplore[\s\-]+[Cc]ompatib\w*',
    r'Xplore[\s\-]+[Cc]ompliant',
]


def _header_footer_text(page, frac: float = 0.08) -> str:
    try:
        words = page.extract_words() or []
    except Exception:
        return ""
    h = float(page.height)
    return " ".join(w["text"] for w in words
                    if float(w.get("top", 0)) <= h * frac or float(w.get("bottom", 0)) >= h * (1 - frac))


def _find_stamp(pdf, file_bytes: bytes, extra: str = "") -> tuple[bool, str, str]:
    patterns = list(_STAMP_PATTERNS)
    if extra and extra.strip():
        patterns.insert(0, re.escape(extra.strip()))

    def _search(text: str):
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                s, e = max(0, m.start() - 10), min(len(text), m.end() + 40)
                return text[s:e].strip()
        return None

    # 1. Document info dictionary
    try:
        meta = pdf.metadata or {}
        meta_str = " ".join(_decode_meta(v) for v in meta.values() if v)
        hit = _search(meta_str)
        if hit:
            return True, "PDF metadata", hit
    except Exception:
        pass
    # 2. XMP metadata packets only (not arbitrary content streams)
    try:
        raw = file_bytes.decode("latin-1", errors="ignore")
        for m in re.finditer(r'<x:xmpmeta.*?</x:xmpmeta>', raw, re.DOTALL | re.IGNORECASE):
            hit = _search(m.group(0))
            if hit:
                return True, "XMP metadata", hit[:80]
    except Exception:
        pass
    # 3. Header / footer zones of the pages (where a stamp would be printed)
    for page in pdf.pages:
        hit = _search(_header_footer_text(page))
        if hit:
            return True, "page header/footer", hit
    return False, "", ""


# ── main checker ──────────────────────────────────────────────────────────────

async def check_blind_compliance_llm(page_text: str, filename: str) -> dict:
    """
    Use LLM to check blind compliance.
    Returns: { passed: bool, signals: [str], explanation: str }
    """
    import llm_provider, json as _json

    system = """You are a blind peer review compliance checker for academic papers.
Determine if this paper's first page reveals the identity of its authors.

Check ONLY for:
- Real author names (person names, not technical terms like "Random Forest" or "Brain Tumor")
- Email addresses
- ORCID identifiers  
- Institutional affiliations in the author byline (e.g. "MIT, Cambridge MA")

Do NOT flag:
- Technical terms, dataset names, method names that happen to look like names
- Institution names mentioned in the body text (only flag the author byline area)
- "Anonymous Author", "Anonymous Affiliation" placeholders

Respond with a JSON object ONLY, no other text:
{"passed": true, "signals": [], "explanation": "No identity signals found."}

If violations found:
{"passed": false, "signals": ["Author name: John Smith", "Email: j.smith@mit.edu"], "explanation": "Author names and email found in header."}"""

    # Send full first page — author info can be anywhere on page 1
    text_snippet = page_text[:2000]

    raw = await llm_provider.call_llm(
        system=system,
        user_text=f"Check this paper's first page for author identity signals:\n\n{text_snippet}",
        max_tokens=400,
        task="blind",
    )

    # Strip any markdown fences the model may add despite instructions
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    result = _json.loads(raw)
    return {
        "passed":      bool(result.get("passed", True)),
        "signals":     result.get("signals", []),
        "explanation": result.get("explanation", ""),
    }


_CHECK_FIELDS = (
    "page_count", "font_embedding", "blind_compliance", "author_info_present",
    "copyright_notice", "pdf_express", "text_extraction", "column_layout", "references",
)


def _fail_all(report: PDFCheckReport, value: str, issue: str) -> None:
    for f in _CHECK_FIELDS:
        setattr(report, f, CheckResult(passed=False, value=value, issues=[issue]))


def check_pdf(
    file_bytes: bytes,
    filename: str,
    max_pages: int,
    double_blind: bool,
    copyright_strings: list[str],
    check_camera_ready: bool = False,
    expected_layout: str = "any",
    validation_stamp: str = "",
    use_llm_blind: bool = False,
    author_names: list[str] = None,
    refs_excluded: bool = False,
) -> PDFCheckReport:
    """
    Run all deterministic checks on a PDF.

    Args:
        file_bytes:        Raw PDF bytes
        filename:          Original filename (for reporting)
        max_pages:         Maximum allowed pages
        double_blind:      Whether to run blind compliance check
        copyright_strings: List of acceptable copyright notice strings to search for
        check_camera_ready: If True, flip blind logic — authors SHOULD be present
        expected_layout:   "single", "two-column", or "any" (no check)
        validation_stamp:  Optional extra stamp text to accept as PDF eXpress proof
        refs_excluded:     If True, the page limit applies to body pages only
                           (pages before the references heading)

    Never raises: unreadable / encrypted PDFs and failures inside individual
    checks are reported in the result instead of aborting a batch.
    """
    import io

    copyright_strings = copyright_strings or []
    report = PDFCheckReport(
        filename=filename,
        page_count=CheckResult(passed=False),
        font_embedding=CheckResult(passed=False),
        blind_compliance=CheckResult(passed=False),
        author_info_present=CheckResult(passed=False),
        copyright_notice=CheckResult(passed=False),
        pdf_express=CheckResult(passed=False),
        text_extraction=CheckResult(passed=False),
    )

    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
        n = len(pdf.pages)          # forces parsing of the page tree
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        _fail_all(report, "Could not open (encrypted/corrupt)",
                  f"PDF could not be opened — it may be encrypted, password-protected or corrupt ({msg[:120]})")
        report.error = f"Could not open (encrypted/corrupt): {msg[:200]}"
        return report

    def _run(field_name: str, fn):
        """Run one check; on failure record it in that check only."""
        try:
            fn()
        except Exception as e:
            setattr(report, field_name, CheckResult(
                passed=False, value="Check failed",
                issues=[f"Could not run this check: {str(e)[:150] or e.__class__.__name__}"],
            ))

    try:
        with pdf:
            report.raw_pages = n
            page_texts = [_page_text(p) for p in pdf.pages]
            all_text = "\n".join(page_texts)
            first_page = pdf.pages[0] if n else None
            first_page_text = page_texts[0] if n else ""
            p1_has_text = len(first_page_text.strip()) >= 20

            # ── page count (total, body, references/appendix) ─────────────────
            def _page_count():
                ref_idx, ref_top = _locate_references(pdf, page_texts)
                if ref_idx >= 0:
                    page_h = float(pdf.pages[ref_idx].height or 792)
                    heading_at_top = ref_top is not None and ref_top <= page_h * 0.15
                    report.body_pages = ref_idx + (0 if heading_at_top else 1)
                else:
                    report.body_pages = n
                report.reference_pages = n - report.body_pages
                counted = report.body_pages if refs_excluded else n
                passed = counted <= max_pages
                issues = []
                if not passed:
                    if refs_excluded:
                        issues.append(f"{counted} body pages (excluding references) exceed limit of {max_pages}")
                    else:
                        issues.append(f"{n} pages exceeds limit of {max_pages}")
                report.page_count = CheckResult(passed=passed, value=str(n), issues=issues)
            _run("page_count", _page_count)

            # ── text extraction ───────────────────────────────────────────────
            def _text_extraction():
                report.raw_text_sample = all_text[:500]
                has_text = len(all_text.strip()) > 100
                empty_pages = sum(1 for t in page_texts if len(t.strip()) < 20)
                issues = [] if has_text else ["PDF appears to be scanned or image-only — text extraction failed"]
                if has_text and empty_pages:
                    issues.append(f"{empty_pages} page(s) have no extractable text (scanned/image pages?)")
                report.text_extraction = CheckResult(
                    passed=has_text,
                    value=f"{len(all_text)} chars extracted",
                    issues=issues,
                )
            _run("text_extraction", _text_extraction)

            # ── font embedding (font descriptors: FontFile/FontFile2/FontFile3) ─
            def _fonts():
                report.font_embedding = _check_font_embedding(pdf)
            _run("font_embedding", _fonts)

            # ── blind compliance (submission) ─────────────────────────────────
            def _blind():
                if not (double_blind and not check_camera_ready):
                    report.blind_compliance = CheckResult(passed=True, value="Not required")
                    return
                hits: list[str] = []
                # Always: metadata (Author/Creator/e-mails)
                hits += _metadata_identity_hits(pdf)
                if first_page is not None and p1_has_text:
                    zone_lines = _top_zone_lines(first_page, 0.30)
                    author_block = " ".join(zone_lines)
                    # Anonymisation placeholders only suppress the weak
                    # "looks like a person's name" heuristic.
                    is_anonymised = any(
                        any(mk in ln.lower() for mk in _ANON_MARKERS) for ln in zone_lines
                    )
                    # Always: real author names from the author list (strongest signal)
                    known = _known_author_hits(first_page_text, author_names or [])
                    if known:
                        hits.append(f"Author name(s) from author list: {', '.join(known[:3])}")
                    # Always: e-mails anywhere on page 1 (not template placeholders), ORCID in header
                    for m in _EMAIL_RE.finditer(first_page_text):
                        if not _is_placeholder_email(m.group(0)):
                            hits.append(f"Email: {m.group(0)}")
                    if _ORCID_RE.search(author_block):
                        hits.append("ORCID identifier found")
                    # Affiliation keywords in header lines (skip placeholder lines)
                    for ln in zone_lines:
                        if "anonym" in ln.lower():
                            continue
                        mm = _AFF_RE.search(ln)
                        if mm:
                            hits.append(f"Affiliation keyword: '{mm.group(0)}'")
                            break
                    if not is_anonymised and not known:
                        name_hits = []
                        for m in _NAME_RE.finditer(" ".join(_author_block_lines(first_page))):
                            if _is_likely_name(m.group(1), m.group(2)):
                                name_hits.append(f"{m.group(1)} {m.group(2)}")
                            if len(name_hits) >= 3:
                                break
                        if name_hits:
                            hits.append(f"Possible author name(s): {', '.join(name_hits[:3])}")

                hits = list(dict.fromkeys(hits))[:6]
                report._det_blind_hits = hits

                if use_llm_blind:
                    # LLM check runs in check_pdf_async; deterministic hits are merged there
                    report._llm_blind_pending = (first_page_text, filename)

                if hits:
                    report.blind_compliance = CheckResult(
                        passed=False, value=f"{len(hits)} identity signal(s) detected", issues=hits,
                    )
                elif first_page is None or not p1_has_text:
                    report.blind_compliance = CheckResult(
                        passed=False, value="Could not verify (no text layer)",
                        issues=["Page 1 has no extractable text (scanned/image PDF) — check anonymisation manually"],
                    )
                else:
                    report.blind_compliance = CheckResult(passed=True, value="Clean")
            _run("blind_compliance", _blind)

            # ── copyright notice (bottom of page 1) ───────────────────────────
            def _copyright():
                if not check_camera_ready:
                    report.copyright_notice = CheckResult(passed=True, value="N/A (submission mode)")
                    return
                if not copyright_strings:
                    report.copyright_notice = CheckResult(passed=True, value="No notices configured")
                    return
                if first_page is None or not p1_has_text:
                    report.copyright_notice = CheckResult(
                        passed=False, value="Could not verify (no text layer)",
                        issues=["Page 1 has no extractable text — check the copyright notice manually"],
                    )
                    return
                p1 = first_page
                footer_y_threshold = p1.height * 0.85
                try:
                    footer_text = " ".join(
                        w["text"] for w in p1.extract_words()
                        if w.get("top", 0) >= footer_y_threshold
                    ).lower()
                except Exception:
                    footer_text = ""
                full_p1 = first_page_text.lower()
                found_notice, found_in_footer = None, False
                for notice in copyright_strings:
                    key_tokens = [t for t in re.split(r'\s+', str(notice).lower()) if len(t) > 3]
                    matched_tokens = sum(1 for t in key_tokens if t in full_p1)
                    if key_tokens and matched_tokens >= max(1, len(key_tokens) * 0.6):
                        found_notice = str(notice)
                        footer_tokens = sum(1 for t in key_tokens if t in footer_text)
                        found_in_footer = footer_tokens >= max(1, len(key_tokens) * 0.5)
                        break
                if found_notice:
                    location = "footer (bottom-left)" if found_in_footer else "page 1 (not in footer)"
                    report.copyright_notice = CheckResult(
                        passed=True, value=f"Found in {location}: {found_notice[:60]}",
                    )
                else:
                    report.copyright_notice = CheckResult(
                        passed=False, value="Not found on page 1",
                        issues=[
                            f"Copyright notice not found on first page. "
                            f"Expected one of: {'; '.join(str(x)[:40] for x in copyright_strings[:3])}"
                        ],
                    )
            _run("copyright_notice", _copyright)

            # ── IEEE PDF eXpress validation stamp ─────────────────────────────
            def _express():
                if not check_camera_ready:
                    report.pdf_express = CheckResult(passed=True, value="N/A (submission mode)")
                    return
                found_stamp, stamp_source, stamp_value = _find_stamp(pdf, file_bytes, validation_stamp)
                report.pdf_express = CheckResult(
                    passed=found_stamp,
                    value=f"Validated ({stamp_source}): {stamp_value[:60]}" if found_stamp else "Not found",
                    issues=[] if found_stamp else [
                        "No IEEE PDF eXpress validation stamp found in PDF metadata or page header/footer. "
                        "Upload to ieee-pdf-express.org, validate, then download the certified PDF."
                    ],
                )
            _run("pdf_express", _express)

            # ── author info present (camera-ready) ────────────────────────────
            def _authors():
                if not check_camera_ready:
                    report.author_info_present = CheckResult(passed=True, value="N/A (submission mode)")
                    return
                if first_page is None or not p1_has_text:
                    report.author_info_present = CheckResult(
                        passed=False, value="Could not verify (no text layer)",
                        issues=["Page 1 has no extractable text — check author information manually"],
                    )
                    return
                if author_names:
                    p1_norm = _strip_accents(first_page_text)
                    found_authors, missing_authors = [], []
                    for name in author_names:
                        if not str(name or "").strip():
                            continue
                        (found_authors if _author_on_page(str(name), p1_norm) else missing_authors).append(name)
                    total = len(found_authors) + len(missing_authors)
                    if not missing_authors:
                        report.author_info_present = CheckResult(
                            passed=True, value=f"All {len(found_authors)} author(s) found on page 1",
                        )
                    elif not found_authors:
                        report.author_info_present = CheckResult(
                            passed=False, value="No author names found",
                            issues=["Author names not detected on page 1 — paper may still be anonymised or authors not yet added"],
                        )
                    else:
                        report.author_info_present = CheckResult(
                            passed=False, value=f"{len(found_authors)}/{total} author(s) found",
                            issues=[f"Missing: {', '.join(missing_authors[:5])}"],
                        )
                    return
                # No author list loaded — fall back to generic signal detection
                signals = []
                if _EMAIL_RE.search(first_page_text):
                    signals.append("email address found")
                aff_match = _AFF_RE.findall(first_page_text[:2000])
                if aff_match:
                    signals.append(f"affiliation keyword: {aff_match[0]}")
                for m in _NAME_RE.finditer(first_page_text[:2000]):
                    if _is_likely_name(m.group(1), m.group(2)):
                        signals.append(f"name: {m.group(1)} {m.group(2)}")
                        break
                if signals:
                    report.author_info_present = CheckResult(passed=True, value=", ".join(signals))
                else:
                    report.author_info_present = CheckResult(
                        passed=False, value="No author signals detected",
                        issues=["No author name, affiliation, or email detected on page 1. Load the author list in Data Import for precise checking."],
                    )
            _run("author_info_present", _authors)

            # ── references section ────────────────────────────────────────────
            def _refs():
                ref_found, ref_count, ref_issues = _detect_references(pdf, page_texts)
                if ref_found:
                    report.references = CheckResult(
                        passed=True,
                        value=f"{ref_count} reference{'s' if ref_count != 1 else ''} found",
                        issues=ref_issues,
                    )
                else:
                    report.references = CheckResult(passed=False, value="Not found", issues=ref_issues)
            _run("references", _refs)

            # ── citations vs reference list (numeric styles) ─────────────────
            def _citations():
                import references as refs_mod
                text = refs_mod.extract_reading_text(pdf)
                report.reading_text = text
                a = refs_mod.analyse_citations(text)
                report.reference_entries = a["entries"]
                if a["status"] == "no_references":
                    report.citations = CheckResult(passed=True, value="Not checked (no reference list)")
                    return
                if a["status"] != "ok":
                    report.citations = CheckResult(passed=True, value="Not checked (author-year style)")
                    return
                issues = []
                if a["missing"]:
                    issues.append("Cited but not in reference list: " + ", ".join(f"[{n}]" for n in a["missing"]))
                if a["uncited"]:
                    issues.append("In reference list but never cited: " + ", ".join(f"[{n}]" for n in a["uncited"]))
                n = len(a["entries"])
                value = (f"All {n} references cited" if not issues else
                         f"{len(a['uncited'])} uncited, {len(a['missing'])} missing of {n}")
                report.citations = CheckResult(passed=not issues, value=value, issues=issues)
            _run("citations", _citations)

            # ── column layout ─────────────────────────────────────────────────
            def _layout():
                if expected_layout not in ("single", "two-column"):
                    report.column_layout = CheckResult(passed=True, value="Not checked")
                    return
                layouts = [d for d in (_detect_column_layout(p) for p in pdf.pages[:3]) if d != "unknown"]
                if not layouts:
                    report.column_layout = CheckResult(
                        passed=True, value="Unknown",
                        issues=["Could not determine layout — possibly scanned or image-only"],
                    )
                    return
                two_col_votes = layouts.count("two-column")
                detected = "two-column" if two_col_votes > len(layouts) / 2 else "single"
                passed = detected == expected_layout
                report.column_layout = CheckResult(
                    passed=passed, value=detected,
                    issues=[] if passed else [f"Expected {expected_layout} layout but detected {detected}"],
                )
            _run("column_layout", _layout)

    except Exception as e:
        report.error = str(e)

    return report


async def check_pdf_async(
    file_bytes: bytes,
    filename: str,
    max_pages: int,
    double_blind: bool,
    copyright_strings: list[str],
    check_camera_ready: bool = False,
    expected_layout: str = "any",
    validation_stamp: str = "",
    use_llm_blind: bool = False,
    author_names: list[str] = None,
    refs_excluded: bool = False,
) -> PDFCheckReport:
    """
    Async version of check_pdf. When use_llm_blind=True, calls the LLM
    natively without threading hacks. Deterministic e-mail / ORCID / metadata
    signals are always merged into the LLM verdict.
    """
    report = check_pdf(
        file_bytes=file_bytes,
        filename=filename,
        max_pages=max_pages,
        double_blind=double_blind,
        copyright_strings=copyright_strings,
        check_camera_ready=check_camera_ready,
        expected_layout=expected_layout,
        validation_stamp=validation_stamp,
        use_llm_blind=use_llm_blind,
        author_names=author_names,
        refs_excluded=refs_excluded,
    )

    if use_llm_blind and hasattr(report, '_llm_blind_pending'):
        page_text, fname = report._llm_blind_pending
        del report._llm_blind_pending
        det_hits = [h for h in getattr(report, "_det_blind_hits", [])
                    if not h.startswith("Possible author name")]
        if not page_text.strip():
            pass  # keep deterministic result (no text layer for the LLM either)
        else:
            try:
                llm_result = await check_blind_compliance_llm(page_text, fname)
                signals = list(dict.fromkeys(list(llm_result["signals"] or []) + det_hits))
                passed = bool(llm_result["passed"]) and not det_hits
                report.blind_compliance = CheckResult(
                    passed=passed,
                    value=llm_result["explanation"] if passed else f"{len(signals)} identity signal(s) detected",
                    issues=[] if passed else signals,
                )
            except Exception as e:
                report.blind_compliance = CheckResult(
                    passed=False,
                    value="AI check error — see details",
                    issues=[f"LLM blind check failed: {str(e)[:150]}. Check your API key in Settings."] + det_hits,
                )

    return report


def report_to_dict(r: PDFCheckReport) -> dict:
    """Serialise a PDFCheckReport to a plain dict for JSON response."""
    def cr(c: CheckResult) -> dict:
        return {"passed": c.passed, "value": c.value, "issues": c.issues}
    return {
        "filename": r.filename,
        "raw_pages": r.raw_pages,
        "body_pages": r.body_pages,
        "reference_pages": r.reference_pages,
        "page_count": cr(r.page_count),
        "font_embedding": cr(r.font_embedding),
        "blind_compliance": cr(r.blind_compliance),
        "author_info_present": cr(r.author_info_present),
        "copyright_notice": cr(r.copyright_notice),
        "pdf_express": cr(r.pdf_express),
        "text_extraction": cr(r.text_extraction),
        "column_layout": cr(r.column_layout),
        "references": cr(r.references),
        "citations": cr(r.citations),
        "reference_entries": r.reference_entries,
        "error": r.error,
    }
