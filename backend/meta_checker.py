"""
meta_checker.py — deterministic validation of EasyChair submission metadata.
Operates on parsed rows from XLSX/CSV. No LLM calls.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
import bisect
from rapidfuzz import fuzz, process


@dataclass
class FieldIssue:
    row_id: str
    field: str
    issue: str


@dataclass
class MetaCheckReport:
    total: int
    issues: list[FieldIssue] = field(default_factory=list)
    duplicate_titles: list[dict] = field(default_factory=list)
    missing_fields_summary: dict = field(default_factory=dict)
    per_row: list[dict] = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(row: dict, *keys) -> str:
    for k in keys:
        for candidate in [k, k.lower(), k.upper(), k.title()]:
            v = row.get(candidate, "")
            if v:
                return str(v).strip()
    return ""


def _word_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0


def _norm_title(t: str) -> str:
    t = re.sub(r"[^\w\s]", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _title_similarity(a: str, b: str) -> float:
    """Normalised Indel similarity (0-1) via rapidfuzz (C implementation)."""
    return fuzz.ratio(_norm_title(a), _norm_title(b)) / 100.0


def _find_duplicate_titles(titles: list[dict], threshold: float) -> list[dict]:
    """Near-duplicate title pairs without a full O(n^2) Python loop.

    Titles are sorted by normalised length; for the Indel ratio
    2*M/(la+lb) >= t to hold, lb <= la*(2-t)/t, so each title only needs to be
    compared with the following titles inside that length window. rapidfuzz's
    score_cutoff lets it bail out early on non-matching pairs.
    """
    items = [(_norm_title(t["title"]), t) for t in titles]
    items = [it for it in items if it[0]]
    items.sort(key=lambda it: len(it[0]))
    t = max(min(threshold, 1.0), 0.01)
    cutoff = t * 100.0
    max_factor = (2.0 - t) / t
    out = []
    n = len(items)
    norms = [it[0] for it in items]
    lengths = [len(x) for x in norms]
    order = {id(t): k for k, t in enumerate(titles)}
    for i in range(n):
        na, ta = items[i]
        # end of the length window (lengths are sorted)
        end = bisect.bisect_right(lengths, len(na) * max_factor, lo=i + 1)
        if end <= i + 1:
            continue
        # C-level batch scoring of this title against its window
        for _, sc, j in process.extract(
            na, norms[i + 1:end], scorer=fuzz.ratio, processor=None,
            score_cutoff=cutoff, limit=None,
        ):
            tb = items[i + 1 + j][1]
            if sc >= cutoff:
                # keep original (input) order inside the pair
                a, b = (ta, tb) if order[id(ta)] < order[id(tb)] else (tb, ta)
                out.append({
                    "id_a": a["id"], "title_a": a["title"],
                    "id_b": b["id"], "title_b": b["title"],
                    "similarity": round(sc / 100.0, 3),
                })
    out.sort(key=lambda d: -d["similarity"])
    return out


# ── main checker ──────────────────────────────────────────────────────────────

def check_metadata(
    rows: list[dict],
    required_fields: list[str] = None,
    min_abstract_words: int = 50,
    max_abstract_words: int = 300,
    min_keywords: int = 3,
    max_keywords: int = 8,
    valid_tracks: list[str] = None,
    duplicate_threshold: float = 0.85,
) -> MetaCheckReport:
    """
    Validate submission metadata rows from EasyChair export.

    Args:
        rows:                 List of dicts from XLSX/CSV
        required_fields:      Field names that must be non-empty
        min/max_abstract_words: Abstract length bounds
        min/max_keywords:     Keyword count bounds
        valid_tracks:         If provided, flag submissions with unknown tracks
        duplicate_threshold:  Title similarity threshold for duplicate detection
    """
    if required_fields is None:
        required_fields = ["title", "abstract"]

    report = MetaCheckReport(total=len(rows))
    missing_counts: dict[str, int] = {}
    titles = []

    for row in rows:
        row_id = _get(row, "#", "id", "paper_id", "submission_id") or "?"
        per = {"id": row_id, "issues": []}

        # ── required fields ───────────────────────────────────────────────────
        for f in required_fields:
            val = _get(row, f)
            if not val:
                issue = FieldIssue(row_id=row_id, field=f, issue=f"Missing required field: {f}")
                report.issues.append(issue)
                per["issues"].append(issue.issue)
                missing_counts[f] = missing_counts.get(f, 0) + 1

        # ── abstract length ───────────────────────────────────────────────────
        abstract = _get(row, "abstract", "Abstract")
        if abstract:
            wc = _word_count(abstract)
            if wc < min_abstract_words:
                msg = f"Abstract too short: {wc} words (min {min_abstract_words})"
                report.issues.append(FieldIssue(row_id=row_id, field="abstract", issue=msg))
                per["issues"].append(msg)
            elif wc > max_abstract_words:
                msg = f"Abstract too long: {wc} words (max {max_abstract_words})"
                report.issues.append(FieldIssue(row_id=row_id, field="abstract", issue=msg))
                per["issues"].append(msg)

        # ── keywords ──────────────────────────────────────────────────────────
        kw_raw = _get(row, "keywords", "Keywords", "keyword", "Keyword")
        if kw_raw:
            # Support comma, semicolon, or newline separation
            kws = [k.strip() for k in re.split(r'[,;\n]+', kw_raw) if k.strip()]
            if len(kws) < min_keywords:
                msg = f"Too few keywords: {len(kws)} (min {min_keywords})"
                report.issues.append(FieldIssue(row_id=row_id, field="keywords", issue=msg))
                per["issues"].append(msg)
            elif len(kws) > max_keywords:
                msg = f"Too many keywords: {len(kws)} (max {max_keywords})"
                report.issues.append(FieldIssue(row_id=row_id, field="keywords", issue=msg))
                per["issues"].append(msg)

        # ── track validation ──────────────────────────────────────────────────
        if valid_tracks:
            track = _get(row, "track", "Track")
            if track and track not in valid_tracks:
                msg = f"Unknown track: '{track}'"
                report.issues.append(FieldIssue(row_id=row_id, field="track", issue=msg))
                per["issues"].append(msg)

        # ── collect title for duplicate check ─────────────────────────────────
        title = _get(row, "title", "Title")
        if title:
            titles.append({"id": row_id, "title": title})

        per["clean"] = len(per["issues"]) == 0
        report.per_row.append(per)

    # ── duplicate title detection ─────────────────────────────────────────────
    report.duplicate_titles = _find_duplicate_titles(titles, duplicate_threshold)

    report.missing_fields_summary = missing_counts
    return report


def report_to_dict(r: MetaCheckReport) -> dict:
    return {
        "total": r.total,
        "issue_count": len(r.issues),
        "duplicate_count": len(r.duplicate_titles),
        "missing_fields_summary": r.missing_fields_summary,
        "duplicate_titles": r.duplicate_titles,
        "per_row": r.per_row,
        "issues": [
            {"row_id": i.row_id, "field": i.field, "issue": i.issue}
            for i in r.issues
        ],
    }
