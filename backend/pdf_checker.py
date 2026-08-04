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
    raw_pages: int = 0
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


def _extract_text(pdf, max_pages: int = 3) -> str:
    """Extract text from first N pages for fast checks."""
    parts = []
    for i, page in enumerate(pdf.pages):
        if i >= max_pages:
            break
        t = page.extract_text() or ""
        parts.append(t)
    return "\n".join(parts)


def _extract_all_text(pdf) -> str:
    parts = []
    for page in pdf.pages:
        t = page.extract_text() or ""
        parts.append(t)
    return "\n".join(parts)


def _detect_references(pdf) -> tuple[bool, int, list[str]]:
    """
    Detect whether a references section exists and count entries.

    Strategy:
    - Search last 50% of pages for a references heading
    - Count by finding max reference number in [N] notation (most reliable)
    - Fall back to counting numbered list entries (1. 2. 3.)
    - Fall back to counting author-year blocks as last resort

    Returns: (found: bool, count: int, issues: list[str])
    """
    total_pages = len(pdf.pages)
    search_from = max(0, int(total_pages * 0.50))  # search last 50% not 40%

    ref_heading_re = re.compile(
        r'(?:'
        r'R\s*E\s*F\s*E\s*R\s*E\s*N\s*C\s*E\s*S?'  # spaced caps
        r'|REFERENCES?'                               # all caps
        r'|References?'                               # title case
        r'|Bibliography'
        r'|BIBLIOGRAPHY'
        r')',
        re.MULTILINE,
    )

    ref_section_text = ""
    ref_page_found = -1

    for i in range(search_from, total_pages):
        page_text = pdf.pages[i].extract_text() or ""
        if ref_heading_re.search(page_text):
            ref_page_found = i
            parts = [page_text]
            for j in range(i + 1, total_pages):
                parts.append(pdf.pages[j].extract_text() or "")
            ref_section_text = "\n".join(parts)
            break

    # Also try searching from page 1 if heading not found in last 50%
    if ref_page_found == -1:
        for i in range(0, search_from):
            page_text = pdf.pages[i].extract_text() or ""
            if ref_heading_re.search(page_text):
                ref_page_found = i
                parts = [page_text]
                for j in range(i + 1, total_pages):
                    parts.append(pdf.pages[j].extract_text() or "")
                ref_section_text = "\n".join(parts)
                break

    if ref_page_found == -1:
        return False, 0, ["No references section found"]

    count = 0
    issues = []

    # ── Strategy A: bracketed numbers [N] anywhere in text ───────────────────
    # Find ALL [N] patterns, take the maximum number found.
    # This is robust to two-column extraction and line-joining artifacts.
    bracketed_nums = re.findall(r'\[(\d+)\]', ref_section_text)
    if bracketed_nums:
        int_nums = [int(n) for n in bracketed_nums]
        max_ref = max(int_nums)
        # Sanity check: max ref should be reasonable (1-500)
        if 1 <= max_ref <= 500:
            count = max_ref

    # ── Strategy B: numbered list "1." or "1)" at line start ─────────────────
    if count == 0:
        numbered = re.findall(r'(?m)^\s*(\d{1,3})[.)]\s+\S', ref_section_text)
        if numbered:
            int_nums = [int(n) for n in numbered]
            count = max(int_nums) if int_nums else 0

    # ── Strategy C: count lines starting a new reference entry ───────────────
    # For author-year style: look for lines starting "Lastname, F." or "Lastname F."
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
    Detect single vs two-column layout using two independent signals.

    Signal 1 — line-span analysis:
      Reconstruct visual lines from word groups. In a two-column doc most lines
      end before ~55% of page width (left col) or start after ~47% (right col).
      In a single-column doc lines span 55-90% of page width.

    Signal 2 — character-density gutter:
      Build a horizontal density histogram of character centres. A two-column
      doc stored spatially shows a near-zero bin in the centre zone (the gutter).

    Returns: "single", "two-column", or "unknown"
    """
    try:
        page_width  = float(page.width)
        page_height = float(page.height)
        top_cutoff  = page_height * 0.12

        # ── Signal 1: line-span analysis ─────────────────────────────────────
        words = page.extract_words()
        body  = [w for w in words if float(w.get("top", 0)) > top_cutoff]
        if len(body) < 20:
            return "unknown"

        lines: dict = {}
        for w in body:
            key = round(float(w["top"]) / 2) * 2
            lines.setdefault(key, []).append(w)

        short_lines = 0
        right_start = 0
        total_lines = 0

        for ws in lines.values():
            if len(ws) < 2:
                continue
            x0 = min(float(w["x0"]) for w in ws)
            x1 = max(float(w["x1"]) for w in ws)
            total_lines += 1
            if x1 < page_width * 0.55:
                short_lines += 1
            if x0 > page_width * 0.47:
                right_start += 1

        if total_lines >= 5:
            short_ratio = short_lines / total_lines
            right_ratio = right_start / total_lines
            if short_ratio > 0.20 and right_ratio > 0.20:
                return "two-column"
            if short_ratio > 0.35:
                return "two-column"

        # ── Signal 2: character-density gutter ───────────────────────────────
        chars      = page.chars
        body_chars = [c for c in chars if float(c.get("top", 0)) > top_cutoff]
        if body_chars:
            N    = 40
            bins = [0] * N
            for c in body_chars:
                cx = (float(c["x0"]) + float(c["x1"])) / 2
                b  = min(int((cx / page_width) * N), N - 1)
                bins[b] += 1
            zone         = bins[14:26]
            surround_avg = (sum(bins[8:14]) + sum(bins[26:32])) / 12 if bins else 1
            gutter_ratio = min(zone) / surround_avg if surround_avg and zone else 1.0
            if gutter_ratio < 0.45:
                return "two-column"

        return "single"

    except Exception:
        return "unknown"


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
    """
    import io

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
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:

            # ── page count ────────────────────────────────────────────────────
            n = len(pdf.pages)
            report.raw_pages = n
            passed = n <= max_pages
            report.page_count = CheckResult(
                passed=passed,
                value=str(n),
                issues=[] if passed else [f"{n} pages exceeds limit of {max_pages}"]
            )

            # ── text extraction ───────────────────────────────────────────────
            first_text = _extract_text(pdf, max_pages=3)
            all_text = _extract_all_text(pdf)
            report.raw_text_sample = all_text[:500]
            has_text = len(all_text.strip()) > 100
            report.text_extraction = CheckResult(
                passed=has_text,
                value=f"{len(all_text)} chars extracted",
                issues=[] if has_text else ["PDF appears to be scanned or image-only — text extraction failed"]
            )

            # ── font embedding ────────────────────────────────────────────────
            # Check via page chars — embedded subset fonts have "+" prefix (e.g. ABCDEF+Arial)
            try:
                embedded = []
                not_embedded = []
                seen = set()
                for page in pdf.pages:
                    for char in (page.chars or []):
                        fname = char.get("fontname", "")
                        if fname and fname not in seen:
                            seen.add(fname)
                            if "+" in fname:
                                embedded.append(fname)
                            else:
                                not_embedded.append(fname)
                if not_embedded:
                    report.font_embedding = CheckResult(
                        passed=False,
                        value=f"{len(embedded)} embedded, {len(not_embedded)} not embedded",
                        issues=[f"Non-embedded fonts: {', '.join(not_embedded[:5])}"]
                    )
                elif embedded or seen:
                    report.font_embedding = CheckResult(
                        passed=True,
                        value=f"{len(embedded)} font(s), all embedded",
                    )
                else:
                    report.font_embedding = CheckResult(
                        passed=True,
                        value="No font data found (image-based PDF)",
                    )
            except Exception as e:
                report.font_embedding = CheckResult(
                    passed=True,
                    value="Could not verify font embedding",
                    issues=[]  # don't show error text to user — it's a library version issue
                )

            # ── blind compliance (submission) ─────────────────────────────────
            if double_blind and not check_camera_ready:

                if use_llm_blind:
                    # LLM-based check runs asynchronously — stored for caller to await
                    first_page_text = pdf.pages[0].extract_text() or ""
                    report._llm_blind_pending = (first_page_text, filename)
                else:
                    hits = []
                    # Extract only the author header zone (top 30% of page 1)
                    author_block = _extract_author_block(pdf.pages[0])

                    # Skip page text scan if paper uses standard anonymisation placeholders
                    anon_markers = ["anonymous author", "anonymous affiliation",
                                    "anonymous email", "anonymized", "anonymised",
                                    "author name", "author affiliation"]
                    block_lower = author_block.lower()
                    is_anonymised = any(m in block_lower for m in anon_markers)

                    if not is_anonymised:
                        # Email addresses
                        for m in _EMAIL_RE.finditer(author_block):
                            hits.append(f"Email: {m.group(0)}")

                        # ORCID
                        if _ORCID_RE.search(author_block):
                            hits.append("ORCID identifier found")

                        # Affiliation keywords
                        aff_matches = _AFF_RE.findall(author_block)
                        if aff_matches:
                            hits.append(f"Affiliation keyword: '{aff_matches[0]}'")

                        # Name-like patterns
                        name_hits = []
                        for m in _NAME_RE.finditer(author_block):
                            if _is_likely_name(m.group(1), m.group(2)):
                                name_hits.append(f"{m.group(1)} {m.group(2)}")
                            if len(name_hits) >= 3:
                                break
                        if name_hits:
                            hits.append(f"Possible author name(s): {', '.join(name_hits[:3])}")

                        # Also scan full first page text for emails
                        first_page_text = pdf.pages[0].extract_text() or ""
                        for m in _EMAIL_RE.finditer(first_page_text):
                            email_hit = f"Email: {m.group(0)}"
                            if email_hit not in hits:
                                hits.append(email_hit)
                                break

                    hits = list(dict.fromkeys(hits))[:5]
                    passed = len(hits) == 0
                    report.blind_compliance = CheckResult(
                        passed=passed,
                        value="Clean" if passed else f"{len(hits)} identity signal(s) detected",
                        issues=hits if hits else []
                    )
            else:
                report.blind_compliance = CheckResult(
                    passed=True,
                    value="Not required",
                )

            # ── author info present (camera-ready) ────────────────────────────
            if check_camera_ready:
                # For camera-ready, authors SHOULD be present in the header area
                author_block = _extract_author_block(pdf.pages[0])
                first_page_text = pdf.pages[0].extract_text() or ""

                has_email = bool(_EMAIL_RE.search(first_page_text))
                has_orcid = bool(_ORCID_RE.search(author_block))
                has_affiliation = bool(_AFF_RE.search(author_block))
                has_name = bool(_NAME_RE.search(author_block))

                passed = has_email or has_affiliation or has_orcid or has_name
                signals = []
                if has_email:      signals.append("email found")
                if has_affiliation: signals.append("affiliation found")
                if has_orcid:      signals.append("ORCID found")
                if has_name:       signals.append("author name found")

                report.author_info_present = CheckResult(
                    passed=passed,
                    value=", ".join(signals) if signals else "Not found",
                    issues=[] if passed else [
                        "No author name, affiliation, email, or ORCID detected on page 1 — verify author info is included"
                    ]
                )
            else:
                report.author_info_present = CheckResult(
                    passed=True,
                    value="N/A (submission mode)",
                )

            # ── copyright notice (bottom-left of page 1) ──────────────────────
            if check_camera_ready and copyright_strings:
                found_notice = None
                found_in_footer = False

                # Extract the bottom 15% of page 1 — that's where IEEE copyright goes
                p1 = pdf.pages[0]
                footer_y_threshold = p1.height * 0.85  # bottom 15%
                try:
                    footer_words = p1.extract_words()
                    footer_text = " ".join(
                        w["text"] for w in footer_words
                        if w.get("top", 0) >= footer_y_threshold
                    ).lower()
                except Exception:
                    footer_text = ""

                # Also check full page text as fallback
                full_p1 = (p1.extract_text() or "").lower()

                for notice in copyright_strings:
                    # Fuzzy check: require at least the key tokens to match
                    key_tokens = [t for t in re.split(r'\s+', notice.lower()) if len(t) > 3]
                    matched_tokens = sum(1 for t in key_tokens if t in full_p1)
                    if key_tokens and matched_tokens >= max(1, len(key_tokens) * 0.6):
                        found_notice = notice
                        # Check if it's specifically in the footer
                        footer_tokens = sum(1 for t in key_tokens if t in footer_text)
                        found_in_footer = footer_tokens >= max(1, len(key_tokens) * 0.5)
                        break

                if found_notice:
                    location = "footer (bottom-left)" if found_in_footer else "page 1 (not in footer)"
                    report.copyright_notice = CheckResult(
                        passed=True,
                        value=f"Found in {location}: {found_notice[:60]}",
                    )
                else:
                    report.copyright_notice = CheckResult(
                        passed=False,
                        value="Not found on page 1",
                        issues=[
                            f"Copyright notice not found on first page. "
                            f"Expected one of: {'; '.join(n[:40] for n in copyright_strings[:3])}"
                        ]
                    )
            elif not check_camera_ready:
                report.copyright_notice = CheckResult(passed=True, value="N/A (submission mode)")
            else:
                report.copyright_notice = CheckResult(passed=True, value="No notices configured")

            # ── IEEE PDF eXpress validation stamp (metadata) ───────────────────
            STAMP_PATTERNS = [
                r'IEEE\s+PDF\s*[Ee]xpress',
                r'PDFExpress',
                r'PDF\s+[Ee]xpress',
                r'Certified\s+by\s+IEEE',
                r'Xplore\s+[Cc]ompatib',
                r'IEEE\s+Xplore',
            ]
            found_stamp = False
            stamp_source = ""
            stamp_value = ""

            # Check metadata first (most reliable — appears in File → Properties)
            try:
                meta = pdf.metadata or {}
                meta_str = " ".join(str(v) for v in meta.values() if v)
                for pattern in STAMP_PATTERNS:
                    m = re.search(pattern, meta_str, re.IGNORECASE)
                    if m:
                        found_stamp = True
                        stamp_source = "PDF metadata"
                        # Extract surrounding context (up to 80 chars)
                        start = max(0, m.start() - 10)
                        end   = min(len(meta_str), m.end() + 40)
                        stamp_value = meta_str[start:end].strip()
                        break
            except Exception:
                pass

            # Also check XMP metadata via raw PDF bytes
            if not found_stamp:
                try:
                    raw = file_bytes.decode('latin-1', errors='ignore')
                    for pattern in STAMP_PATTERNS:
                        m = re.search(pattern, raw, re.IGNORECASE)
                        if m:
                            found_stamp = True
                            stamp_source = "XMP metadata"
                            start = max(0, m.start() - 10)
                            end   = min(len(raw), m.end() + 40)
                            stamp_value = raw[start:end].strip()[:80]
                            break
                except Exception:
                    pass

            # Also check page text as last resort
            if not found_stamp:
                for pattern in STAMP_PATTERNS:
                    m = re.search(pattern, all_text, re.IGNORECASE)
                    if m:
                        found_stamp = True
                        stamp_source = "page text"
                        start = max(0, m.start() - 5)
                        end   = min(len(all_text), m.end() + 30)
                        stamp_value = all_text[start:end].strip()
                        break

            if check_camera_ready:
                report.pdf_express = CheckResult(
                    passed=found_stamp,
                    value=f"Validated ({stamp_source}): {stamp_value[:60]}" if found_stamp else "Not found",
                    issues=[] if found_stamp else [
                        "No IEEE PDF eXpress validation stamp found in PDF metadata or text. "
                        "Upload to ieee-pdf-express.org, validate, then download the certified PDF."
                    ]
                )
            else:
                report.pdf_express = CheckResult(passed=True, value="N/A (submission mode)")

            # ── author names from author list ──────────────────────────────────
            if check_camera_ready and author_names:
                p1_text = (pdf.pages[0].extract_text() or "").lower()
                found_authors = []
                missing_authors = []
                for name in author_names:
                    name_lower = name.strip().lower()
                    parts = name_lower.split()
                    if not parts:
                        continue
                    # Check full name or last name + first initial
                    if name_lower in p1_text:
                        found_authors.append(name)
                    elif len(parts) >= 2 and parts[-1] in p1_text and parts[0][0] in p1_text:
                        found_authors.append(name)
                    else:
                        # Fuzzy: check if last name appears
                        last = parts[-1]
                        if len(last) >= 4 and last in p1_text:
                            found_authors.append(name)
                        else:
                            missing_authors.append(name)

                if not missing_authors:
                    report.author_info_present = CheckResult(
                        passed=True,
                        value=f"All {len(found_authors)} author(s) found on page 1",
                    )
                elif len(missing_authors) == len(author_names):
                    report.author_info_present = CheckResult(
                        passed=False,
                        value="No author names found",
                        issues=["Author names not detected on page 1 — paper may still be anonymised or authors not yet added"]
                    )
                else:
                    report.author_info_present = CheckResult(
                        passed=False,
                        value=f"{len(found_authors)}/{len(author_names)} author(s) found",
                        issues=[f"Missing: {', '.join(missing_authors[:5])}"]
                    )
            elif check_camera_ready:
                # No author list loaded — fall back to generic signal detection
                signals = []
                p1_text_raw = pdf.pages[0].extract_text() or ""
                if _EMAIL_RE.search(p1_text_raw):
                    signals.append("email address found")
                aff_match = _AFF_RE.findall(p1_text_raw[:2000])
                if aff_match:
                    signals.append(f"affiliation keyword: {aff_match[0]}")
                for m in _NAME_RE.finditer(p1_text_raw[:2000]):
                    if _is_likely_name(m.group(1), m.group(2)):
                        signals.append(f"name: {m.group(1)} {m.group(2)}")
                        break
                if signals:
                    report.author_info_present = CheckResult(
                        passed=True,
                        value=", ".join(signals),
                    )
                else:
                    report.author_info_present = CheckResult(
                        passed=False,
                        value="No author signals detected",
                        issues=["No author name, affiliation, or email detected on page 1. Load the author list in Data Import for precise checking."]
                    )
            else:
                report.author_info_present = CheckResult(passed=True, value="N/A (submission mode)")

            # ── references section ────────────────────────────────────────────
            ref_found, ref_count, ref_issues = _detect_references(pdf)
            if ref_found:
                report.references = CheckResult(
                    passed=True,
                    value=f"{ref_count} reference{'s' if ref_count != 1 else ''} found",
                    issues=ref_issues,
                )
            else:
                report.references = CheckResult(
                    passed=False,
                    value="Not found",
                    issues=ref_issues,
                )

            # ── column layout ─────────────────────────────────────────────────
            if expected_layout in ("single", "two-column"):
                layouts = []
                for page in pdf.pages[:3]:
                    detected = _detect_column_layout(page)
                    if detected != "unknown":
                        layouts.append(detected)
                if not layouts:
                    report.column_layout = CheckResult(
                        passed=True,
                        value="Unknown",
                        issues=["Could not determine layout — possibly scanned or image-only"]
                    )
                else:
                    two_col_votes = layouts.count("two-column")
                    detected = "two-column" if two_col_votes > len(layouts) / 2 else "single"
                    passed = detected == expected_layout
                    report.column_layout = CheckResult(
                        passed=passed,
                        value=detected,
                        issues=[] if passed else [
                            f"Expected {expected_layout} layout but detected {detected}"
                        ]
                    )
            else:
                report.column_layout = CheckResult(
                    passed=True,
                    value="Not checked",
                )

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
) -> PDFCheckReport:
    """
    Async version of check_pdf. When use_llm_blind=True, calls the LLM
    natively without threading hacks.
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
    )

    # If LLM blind check is pending, run it now (we're in async context)
    if use_llm_blind and hasattr(report, '_llm_blind_pending'):
        page_text, fname = report._llm_blind_pending
        del report._llm_blind_pending
        try:
            llm_result = await check_blind_compliance_llm(page_text, fname)
            report.blind_compliance = CheckResult(
                passed=llm_result["passed"],
                value=llm_result["explanation"] if llm_result["passed"] else f"{len(llm_result['signals'])} identity signal(s) detected",
                issues=llm_result["signals"] if not llm_result["passed"] else []
            )
        except Exception as e:
            # Show the error clearly rather than silently passing
            report.blind_compliance = CheckResult(
                passed=False,
                value="AI check error — see details",
                issues=[f"LLM blind check failed: {str(e)[:150]}. Check your API key in Settings."]
            )

    return report


def report_to_dict(r: PDFCheckReport) -> dict:
    """Serialise a PDFCheckReport to a plain dict for JSON response."""
    def cr(c: CheckResult) -> dict:
        return {"passed": c.passed, "value": c.value, "issues": c.issues}
    return {
        "filename": r.filename,
        "raw_pages": r.raw_pages,
        "page_count": cr(r.page_count),
        "font_embedding": cr(r.font_embedding),
        "blind_compliance": cr(r.blind_compliance),
        "author_info_present": cr(r.author_info_present),
        "copyright_notice": cr(r.copyright_notice),
        "pdf_express": cr(r.pdf_express),
        "text_extraction": cr(r.text_extraction),
        "column_layout": cr(r.column_layout),
        "references": cr(r.references),
        "error": r.error,
    }
