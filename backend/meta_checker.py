"""
meta_checker.py — deterministic validation of EasyChair submission metadata.
Operates on parsed rows from XLSX/CSV. No LLM calls.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from difflib import SequenceMatcher


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


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


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
    seen_pairs = set()
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            pair_key = (titles[i]["id"], titles[j]["id"])
            if pair_key in seen_pairs:
                continue
            sim = _title_similarity(titles[i]["title"], titles[j]["title"])
            if sim >= duplicate_threshold:
                report.duplicate_titles.append({
                    "id_a": titles[i]["id"],
                    "title_a": titles[i]["title"],
                    "id_b": titles[j]["id"],
                    "title_b": titles[j]["title"],
                    "similarity": round(sim, 3),
                })
                seen_pairs.add(pair_key)

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
