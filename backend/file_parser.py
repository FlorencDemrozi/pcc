"""
file_parser.py — universal file format detection and parsing.
Handles CSV, XLSX, and TXT files with format auto-detection.
Built specifically for EasyChair export formats.
"""

import io
import csv
import re
from typing import Optional


# ── Tabular parsers (deterministic) ──────────────────────────────────────────

def parse_csv_bytes(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    for delimiter in [",", ";", "\t", "|"]:
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = [dict(r) for r in reader]
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            continue
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def parse_xlsx_bytes(content: bytes) -> list[dict]:
    """Parse XLSX with openpyxl, falling back to direct XML on stylesheet errors."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h or f"col_{i}").strip() for i, h in enumerate(rows[0])]
        result = []
        for row in rows[1:]:
            d = {headers[i]: str(v if v is not None else "").strip()
                 for i, v in enumerate(row)}
            if any(v for v in d.values()):
                result.append(d)
        return result
    except Exception:
        # Fallback: parse raw XML to bypass stylesheet issues (common in EasyChair exports)
        return _parse_xlsx_xml(content)


def _parse_xlsx_xml(content: bytes) -> list[dict]:
    """Direct XML XLSX parser — bypasses openpyxl stylesheet validation."""
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            # Read shared strings table
            shared = []
            if 'xl/sharedStrings.xml' in z.namelist():
                with z.open('xl/sharedStrings.xml') as f:
                    root = ET.parse(f).getroot()
                    for si in root.findall('.//x:si', ns):
                        shared.append(''.join(t.text or '' for t in si.findall('.//x:t', ns)))
            # Find first worksheet
            sheet = next((n for n in sorted(z.namelist())
                          if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')), None)
            if not sheet:
                return []
            with z.open(sheet) as f:
                root = ET.parse(f).getroot()
            rows_data = []
            for row_el in root.findall('.//x:row', ns):
                row = {}
                for cell in row_el.findall('x:c', ns):
                    ref = cell.get('r', '')
                    col = ''.join(c for c in ref if c.isalpha())
                    t   = cell.get('t', '')
                    v   = cell.find('x:v', ns)
                    if v is not None and v.text is not None:
                        val = (shared[int(v.text)]
                               if t == 's' and int(v.text) < len(shared)
                               else v.text)
                    else:
                        val = ''
                    # Normalise newlines embedded in cell values
                    row[col] = val.replace('\n', ' ').replace('\r', '').strip()
                if row:
                    rows_data.append(row)
        if not rows_data:
            return []
        # Map column letters to header names from first row
        all_cols = sorted({k for r in rows_data for k in r},
                          key=lambda x: (len(x), x))
        headers = {c: rows_data[0].get(c, c) for c in all_cols}
        result = []
        for row in rows_data[1:]:
            if not any(row.values()):
                continue
            result.append({headers[c]: row.get(c, '') for c in all_cols})
        return result
    except Exception:
        return []


# ── EasyChair TXT review file parser ─────────────────────────────────────────

def parse_easychair_review_txt(content: bytes) -> list[dict]:
    """
    Parse EasyChair review export TXT file.

    Format:
    ***** PAPER XXXX *****
    AUTHORS: ...
    TITLE: ...
    PRELIMINARY DECISION: ...
    ================== SUMMARY OF REVIEWS =================
    Reviewer: score (confidence)
    ...
    ++++++++++ REVIEW N (Reviewer Name) +++++++++
    TOTAL SCORE: N
    Overall evaluation: N (label)
    Reviewer's confidence: N (label)
    ---- OVERALL EVALUATION ----
    ...review text...
    ---- CONFIDENTIAL REMARKS FOR THE PROGRAM COMMITTEE ----
    ...
    """
    text = content.decode("utf-8-sig", errors="replace")
    reviews = []

    # Split into paper blocks
    paper_blocks = re.split(r'\*{5,}\s*PAPER\s+(\d+)\s*\*{5,}', text)

    # paper_blocks = [pre_text, paper_id_1, block_1, paper_id_2, block_2, ...]
    i = 1
    while i < len(paper_blocks) - 1:
        paper_id = paper_blocks[i].strip()
        block = paper_blocks[i + 1]
        i += 2

        # Extract paper-level metadata
        authors_m = re.search(r'^AUTHORS?:\s*(.+)', block, re.MULTILINE)
        title_m   = re.search(r'^TITLE:\s*(.+)', block, re.MULTILINE)
        prelim_m  = re.search(r'^PRELIMINARY DECISION:\s*(.+)', block, re.MULTILINE | re.IGNORECASE)

        authors = authors_m.group(1).strip() if authors_m else ""
        title   = title_m.group(1).strip() if title_m else ""
        prelim  = prelim_m.group(1).strip() if prelim_m else ""

        # Split into individual review sections
        review_sections = re.split(r'\+{5,}\s*REVIEW\s+\d+\s*\(([^)]+)\)\s*\+{5,}', block)
        # review_sections = [pre_review_text, reviewer_name_1, section_1, reviewer_name_2, section_2, ...]

        j = 1
        while j < len(review_sections) - 1:
            reviewer_name = review_sections[j].strip()
            section = review_sections[j + 1]
            j += 2

            # Extract fields
            score_m = re.search(r'^TOTAL SCORE:\s*([+-]?\d+)', section, re.MULTILINE)
            eval_m  = re.search(r'^Overall evaluation:\s*([+-]?\d+)', section, re.MULTILINE)
            conf_m  = re.search(r'^Reviewer\'?s?\s+confidence:\s*(\d+)', section, re.MULTILINE | re.IGNORECASE)

            score      = score_m.group(1) if score_m else (eval_m.group(1) if eval_m else "")
            confidence = conf_m.group(1) if conf_m else ""

            # Extract review body text (between ---- OVERALL EVALUATION ---- and ---- CONFIDENTIAL ----)
            body_m = re.search(
                r'----\s*OVERALL EVALUATION\s*----\s*\n(.*?)(?:----\s*CONFIDENTIAL|$)',
                section, re.DOTALL | re.IGNORECASE
            )
            review_text = body_m.group(1).strip() if body_m else section.strip()

            reviews.append({
                "paper_id":   paper_id,
                "title":      title,
                "authors":    authors,
                "preliminary_decision": prelim,
                "reviewer":   reviewer_name,
                "score":      score,
                "confidence": confidence,
                "text":       review_text,
                "_raw":       section.strip(),
            })

    return reviews


def parse_review_summary_xlsx(content: bytes) -> list[dict]:
    """
    Parse EasyChair review_summary.xlsx.
    Columns: #, Authors, Title, Decision, Track,
             Average total score, Average total score weighted by confidence,
             Total score (comma-separated), Overall evaluation (comma-separated),
             Reviewer's confidence (comma-separated)
    Returns one row per paper with individual scores expanded.
    """
    rows = parse_xlsx_bytes(content)
    result = []
    for row in rows:
        paper_id = (row.get("#") or row.get("paper_id") or "").strip()
        if not paper_id:
            continue

        # Parse comma-separated score lists into individual reviewer rows
        scores_raw = (row.get("Total score") or row.get("Overall evaluation") or "").strip()
        confs_raw  = (row.get("Reviewer's confidence") or "").strip()

        scores = [s.strip() for s in scores_raw.split(",") if s.strip()] if scores_raw else []
        confs  = [c.strip() for c in confs_raw.split(",") if c.strip()]  if confs_raw  else []

        if scores:
            for idx, score in enumerate(scores):
                conf = confs[idx] if idx < len(confs) else ""
                result.append({
                    "paper_id":   paper_id,
                    "title":      row.get("Title", ""),
                    "authors":    row.get("Authors", ""),
                    "track":      row.get("Track", ""),
                    "decision":   row.get("Decision", ""),
                    "score":      score,
                    "confidence": conf,
                    "reviewer":   f"Reviewer {idx+1}",
                    "text":       "",
                    "avg_score":  row.get("Average total score", ""),
                })
        else:
            result.append({
                "paper_id":   paper_id,
                "title":      row.get("Title", ""),
                "authors":    row.get("Authors", ""),
                "track":      row.get("Track", ""),
                "decision":   row.get("Decision", ""),
                "score":      row.get("Average total score", ""),
                "confidence": "",
                "reviewer":   "",
                "text":       "",
            })
    return result


def parse_tpc_xlsx(content: bytes) -> list[dict]:
    """
    Parse TPC/PC member list.
    Columns: Name, Surname, Email, Affiliation, Role, Track
    Returns normalised list with: name, email, affiliation, role, track
    """
    rows = parse_xlsx_bytes(content)
    result = []
    for row in rows:
        name = " ".join(filter(None, [
            (row.get("Name") or row.get("First Name") or row.get("FirstName") or "").strip(),
            (row.get("Surname") or row.get("Last Name") or row.get("LastName") or "").strip(),
        ])).strip()
        if not name:
            name = (row.get("name") or row.get("full_name") or "").strip()

        email = (row.get("Email") or row.get("email") or row.get("E-mail") or "").strip()
        aff   = (row.get("Affiliation") or row.get("Affiliaiton") or  # note typo in real file
                 row.get("Institution") or row.get("affiliation") or "").strip()
        role  = (row.get("Role") or row.get("role") or "").strip()
        track = (row.get("Track") or row.get("track") or "").strip()

        if name or email:
            result.append({
                "name":        name,
                "email":       email,
                "affiliation": aff,
                "role":        role,
                "track":       track,
                # Also expose as reviewer fields for COI compatibility
                "reviewer":    name,
                "reviewer_id": email or name,
            })
    return result


def parse_author_list_xlsx(content: bytes) -> list[dict]:
    """
    Parse EasyChair author list XLSX.
    Columns: #, Author, Email, Country, Affiliation, Corresponding?, Submitter?
    Returns one row per author with paper_id, name, email, affiliation.
    """
    rows = parse_xlsx_bytes(content)
    if not rows:
        rows = _parse_xlsx_xml(content)
    result = []
    for row in rows:
        paper_id = (row.get("#") or row.get("paper_id") or row.get("Submission") or "").strip()
        if not paper_id:
            continue
        name  = (row.get("Author")  or row.get("Name") or row.get("author") or "").strip()
        email = (row.get("Email")   or row.get("email") or "").strip()
        aff   = (row.get("Affiliation") or row.get("affiliation") or
                 row.get("Institution") or "").strip()
        country = (row.get("Country") or row.get("country") or "").strip()
        if name or email:
            result.append({
                "paper_id":    paper_id,
                "#":           paper_id,
                "name":        name,
                "author":      name,
                "email":       email,
                "affiliation": aff,
                "country":     country,
            })
    return result


def parse_submissions_xlsx(content: bytes) -> list[dict]:
    """
    Parse EasyChair submissions XLSX.
    Columns: #, Authors, Title, paper, Presentation Format, Track, Time, Decision, Keywords, Abstract
    """
    rows = parse_xlsx_bytes(content)
    result = []
    for row in rows:
        paper_id = (row.get("#") or row.get("paper_id") or row.get("id") or "").strip()
        if not paper_id:
            continue
        result.append({
            "paper_id":   paper_id,
            "#":          paper_id,
            "id":         paper_id,
            "title":      row.get("Title", ""),
            "authors":    row.get("Authors", ""),
            "track":      row.get("Track", ""),
            "decision":   row.get("Decision", ""),
            "keywords":   row.get("Keywords", ""),
            "abstract":   row.get("Abstract", ""),
            "format":     row.get("Presentation Format", ""),
        })
    return result


# ── Format detector ───────────────────────────────────────────────────────────

def _detect_format(content: bytes, filename: str) -> str:
    """
    Detect the specific format of a file to choose the right parser.
    Returns: 'easychair_review_txt', 'review_summary_xlsx',
             'tpc_xlsx', 'submissions_xlsx', 'generic_xlsx', 'generic_csv'
    """
    name = (filename or "").lower()

    if name.endswith(".txt"):
        # Peek at content
        sample = content[:500].decode("utf-8-sig", errors="replace")
        if "LIST OF REVIEWS" in sample or re.search(r'\*{5,}\s*PAPER\s+\d+', sample):
            return "easychair_review_txt"
        return "generic_txt"

    if name.endswith((".xlsx", ".xls")):
        # Peek at first row headers
        try:
            rows = parse_xlsx_bytes(content[:])
            if not rows:
                rows = _parse_xlsx_xml(content)
            if not rows:
                return "generic_xlsx"
            headers = set(k.lower().strip() for k in rows[0].keys())
            # TPC file: has Name/Surname/Role
            if "role" in headers and ("surname" in headers or "name" in headers):
                return "tpc_xlsx"
            # Author list: has Author + Corresponding?/Submitter?/Country
            if "author" in headers and (
                "corresponding?" in headers or "submitter?" in headers or "country" in headers
            ):
                return "author_list_xlsx"
            # Review summary: has "total score" or "average total score"
            if any("total score" in h for h in headers) or any("average" in h for h in headers):
                return "review_summary_xlsx"
            # Submissions: has Abstract or Keywords
            if "abstract" in headers or "keywords" in headers:
                return "submissions_xlsx"
        except Exception:
            pass
        return "generic_xlsx"

    if name.endswith(".csv"):
        return "generic_csv"

    return "unknown"


# ── Universal entry point ─────────────────────────────────────────────────────

async def parse_any_file(
    content: bytes,
    filename: str,
    purpose: str = "structured data",
    use_llm_fallback: bool = True,
) -> list[dict]:
    """
    Parse any uploaded file into a list of dicts.
    Detects format automatically and uses the right parser.
    """
    fmt = _detect_format(content, filename)

    if fmt == "easychair_review_txt":
        rows = parse_easychair_review_txt(content)
        if rows:
            return rows

    elif fmt == "review_summary_xlsx":
        rows = parse_review_summary_xlsx(content)
        if rows:
            return rows

    elif fmt == "tpc_xlsx":
        rows = parse_tpc_xlsx(content)
        if rows:
            return rows

    elif fmt == "author_list_xlsx":
        rows = parse_author_list_xlsx(content)
        if rows:
            return rows

    elif fmt == "submissions_xlsx":
        rows = parse_submissions_xlsx(content)
        if rows:
            return rows

    elif fmt == "generic_xlsx":
        rows = parse_xlsx_bytes(content)
        if rows:
            return rows

    elif fmt == "generic_csv":
        rows = parse_csv_bytes(content)
        if rows:
            return rows

    elif fmt == "generic_txt":
        # Try generic review block parser
        rows = _parse_generic_txt_reviews(content)
        if rows:
            return rows

    # LLM fallback for truly unknown formats
    if use_llm_fallback:
        try:
            rows = await _parse_with_llm(content, filename, purpose)
            if rows:
                return rows
        except Exception:
            pass

    # Last resort
    text = content.decode("utf-8-sig", errors="replace")
    return [{"text": line.strip(), "paper_id": "", "score": ""}
            for line in text.split("\n") if line.strip()]


def _parse_generic_txt_reviews(content: bytes) -> list[dict]:
    """Fallback parser for non-EasyChair review text files."""
    text = content.decode("utf-8-sig", errors="replace")
    reviews = []
    # Try common block separators
    for sep in [r'={3,}', r'-{3,}', r'\*{3,}', r'#{3,}']:
        blocks = re.split(sep, text)
        if len(blocks) >= 2:
            for i, block in enumerate(blocks):
                block = block.strip()
                if len(block) < 30:
                    continue
                score_m = re.search(r'(?:score|rating)[:\s]+([+-]?\d+)', block, re.IGNORECASE)
                conf_m  = re.search(r'confidence[:\s]+(\d+)', block, re.IGNORECASE)
                pid_m   = re.search(r'(?:paper|submission)[:\s#]+(\d+)', block, re.IGNORECASE)
                reviews.append({
                    "paper_id":   pid_m.group(1) if pid_m else str(i),
                    "reviewer":   "",
                    "score":      score_m.group(1) if score_m else "",
                    "confidence": conf_m.group(1) if conf_m else "",
                    "text":       block,
                })
            if reviews:
                return reviews
    return []


async def _parse_with_llm(content: bytes, filename: str, purpose: str) -> list[dict]:
    """LLM fallback for unknown formats."""
    import llm_provider, json
    text = content.decode("utf-8-sig", errors="replace")[:4000]
    system = f"""Extract {purpose} from this file. Return ONLY a JSON array of objects.
For review files use keys: paper_id, reviewer, score, confidence, text
For score files use keys: paper_id, score, confidence, reviewer
For author/PC files use keys: name, email, affiliation
If a field is missing use empty string."""
    raw = await llm_provider.call_llm(system=system, user_text=f"File: {filename}\n\n{text}", max_tokens=2000)
    raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return data if isinstance(data, list) else []
