"""Section 6 -- references.

Local checks: duplicates, numbering, incomplete entries, citation cross-check.
Online (opt-in): DOI exists, DOI metadata matches the entry, retractions and
corrections (Crossref includes Retraction Watch data). Results distinguish
"not found" (could not confirm) from "confirmed incorrect".
"""

import re
import time

from rapidfuzz import fuzz

from .registry import check
from .findings import Finding, ev
from . import docmodel


def _entries(doc):
    return (doc.get("citations") or {}).get("entries") or []


def _norm(s):
    s = re.sub(r'(?i)\b(?:doi|https?://\S+|vol\.?|no\.?|pp\.?|in proc\w*\.?|proceedings of the)\b', ' ', s or "")
    return " ".join(re.sub(r'[^a-z0-9 ]+', ' ', s.lower()).split())


def _ref_page(doc, text):
    return docmodel.find_page(doc, text[:40]) or doc.get("ref_page")


@check("ref_duplicates", "Duplicate reference entries", "references", 6,
       "The same work listed twice in the reference list (often padding or a merge error).",
       params={"similarity": 90})
def ref_duplicates(doc, ctx):
    es = _entries(doc)
    lim = float(ctx.params["similarity"])
    normed = [(e, _norm(e["text"])) for e in es]
    pairs = []
    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            a, b = normed[i][1], normed[j][1]
            if len(a) < 30 or len(b) < 30:
                continue
            if fuzz.token_sort_ratio(a, b) >= lim:
                pairs.append((normed[i][0], normed[j][0]))
    if not pairs:
        return []
    return [Finding("ref_duplicates", "Duplicate reference entries", "issue", "low",
                    f"{len(pairs)} pair(s) of entries describe the same work: "
                    + ", ".join(f"[{a['n']}]=[{b['n']}]" for a, b in pairs[:10]) + ".",
                    [ev(_ref_page(doc, b["text"]), f"[{a['n']}] {a['text'][:110]}  ⇄  [{b['n']}] {b['text'][:110]}", "references")
                     for a, b in pairs[:6]], 0.85,
                    suggested_action="Mention it to the authors; repeated duplicates can indicate inflated reference lists.")]


@check("ref_numbering", "Reference numbering", "references", 6,
       "Numbered reference lists: gaps, repeats and out-of-order numbers.")
def ref_numbering(doc, ctx):
    es = _entries(doc)
    if len(es) < 3:
        return []
    nums = [e["n"] for e in es]
    issues = []
    seen = set()
    rep = sorted({n for n in nums if n in seen or seen.add(n)})
    if rep:
        issues.append(f"repeated: {', '.join(map(str, rep[:10]))}")
    full = set(range(min(nums), max(nums) + 1))
    gaps = sorted(full - set(nums))
    if gaps and len(gaps) <= 10:
        issues.append(f"missing numbers: {', '.join(map(str, gaps))}")
    disorder = sum(1 for a, b in zip(nums, nums[1:]) if b < a)
    if disorder:
        issues.append(f"{disorder} place(s) out of order")
    if min(nums) not in (0, 1):
        issues.append(f"list starts at [{min(nums)}]")
    if not issues:
        return []
    return [Finding("ref_numbering", "Inconsistent reference numbering", "possible", "low",
                    "; ".join(issues).capitalize() + ".",
                    [ev(doc.get("ref_page"), " ".join(f"[{n}]" for n in nums[:40]), "references")], 0.6,
                    limitations="Entries split across columns or pages can confuse the parser.")]


_YEAR = re.compile(r'\b(19[5-9]\d|20[0-4]\d)\b')
_WEB = re.compile(r'(?i)https?://|www\.|online|available|accessed|github|datasheet|standard|ieee std|iso\b|patent|white ?paper|manual')


@check("ref_incomplete", "Incomplete reference entries", "references", 6,
       "Entries that are very short or have no year.",
       params={"min_chars": 35})
def ref_incomplete(doc, ctx):
    bad = []
    for e in _entries(doc):
        t = e["text"]
        reasons = []
        if len(t) < ctx.params["min_chars"]:
            reasons.append("very short")
        if not _YEAR.search(t) and not _WEB.search(t):
            reasons.append("no year")
        if reasons:
            bad.append((e, reasons))
    if not bad:
        return []
    return [Finding("ref_incomplete", "Incomplete reference entries", "possible", "low",
                    f"{len(bad)} entr{'y' if len(bad) == 1 else 'ies'} look incomplete.",
                    [ev(_ref_page(doc, e["text"]), f"[{e['n']}] {e['text'][:140]} ({', '.join(r)})", "references") for e, r in bad[:10]],
                    0.55)]


@check("citation_crosscheck", "Citations vs reference list", "references", 6,
       "Entries never cited in the text, and citations with no matching entry (numbered styles).")
def citation_crosscheck(doc, ctx):
    c = doc.get("citations") or {}
    if c.get("status") != "ok":
        return []
    out = []
    if c.get("missing"):
        out.append(Finding("citation_crosscheck", "Citations without a reference entry", "issue", "medium",
                           "Cited in the text but missing from the list: " + ", ".join(f"[{n}]" for n in c["missing"][:15]) + ".",
                           [ev(None, ", ".join(f"[{n}]" for n in c["missing"][:30]), "references")], 0.75))
    if c.get("uncited"):
        n = len(c["uncited"])
        out.append(Finding("citation_crosscheck", "Reference entries never cited", "possible", "low",
                           f"{n} entr{'y is' if n == 1 else 'ies are'} never cited in the text.",
                           [ev(doc.get("ref_page"), ", ".join(f"[{x}]" for x in c["uncited"][:30]), "references")], 0.65,
                           limitations="Citations inside figures/tables or written as ranges in unusual ways can be missed."))
    return out


# ── Online: DOI resolution, metadata match, retractions ──────────────────────

_DOI = re.compile(r'\b(10\.\d{4,9}/[^\s"<>\]\[]+)', re.I)
_UA = {"User-Agent": "ProgramChairCopilot/1.0 (pre-review screening)"}


def _get(client, url, params=None, tries=4):
    """GET with polite retries on rate limiting (429) and temporary errors (5xx)."""
    r = None
    for i in range(tries):
        r = client.get(url, params=params, headers=_UA)
        if r.status_code not in (429, 500, 502, 503, 504):
            return r
        try:
            wait = float(r.headers.get("Retry-After", "")) if r.headers.get("Retry-After") else 1.5 * (i + 1)
        except ValueError:
            wait = 1.5 * (i + 1)
        time.sleep(min(wait, 10))
    return r


def _clean_doi(d):
    return d.rstrip('.,;:)').rstrip('.')


def _crossref_work(client, store, doi):
    k = "crossref:work:" + doi.lower()
    hit = store.get_lookup(k)
    if hit is not None:
        return hit
    try:
        r = _get(client, f"https://api.crossref.org/works/{doi}")
        if r.status_code == 404:
            data = {"status": "not_found"}
        elif r.status_code == 200:
            m = r.json().get("message", {})
            data = {"status": "ok", "title": " ".join(m.get("title") or []),
                    "year": ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0],
                    "authors": [a.get("family", "") for a in (m.get("author") or [])][:8],
                    "type": m.get("type", "")}
        else:
            return {"status": "error", "code": r.status_code}
    except Exception as e:
        return {"status": "error", "error": type(e).__name__}
    store.put_lookup(k, data)
    return data


def _doi_exists(client, store, doi):
    """doi.org handle API: does the DOI exist at all (any registry, e.g. DataCite)?"""
    k = "doi:exists:" + doi.lower()
    hit = store.get_lookup(k)
    if hit is not None:
        return hit.get("exists")
    try:
        r = _get(client, f"https://doi.org/api/handles/{doi}")
        exists = r.status_code == 200 and r.json().get("responseCode") == 1
        if r.status_code not in (200, 404):
            return None
    except Exception:
        return None
    store.put_lookup(k, {"exists": exists})
    return exists


def _updates(client, store, doi):
    """Retraction / correction / expression-of-concern notices that update this DOI."""
    k = "crossref:updates:" + doi.lower()
    hit = store.get_lookup(k, max_age_s=7 * 86400)
    if hit is not None:
        return hit
    try:
        r = _get(client, "https://api.crossref.org/works", params={"filter": f"updates:{doi}", "rows": 10})
        if r.status_code != 200:
            return None
        items = r.json().get("message", {}).get("items", [])
        notes = []
        for it in items:
            for u in it.get("update-to") or []:
                if (u.get("DOI") or "").lower() == doi.lower():
                    notes.append({"type": u.get("type", ""), "notice": it.get("DOI", "")})
    except Exception:
        return None
    store.put_lookup(k, notes)
    return notes


def _raw_dois(doc):
    """DOIs as printed, with line-break hyphens kept ("...00869-\\nx" -> "...00869-x").
    The reference parser drops those hyphens, which would corrupt hyphenated DOIs."""
    t = doc.get("full_text", "")
    joined = re.sub(r'-[ \t]*\n[ \t]*', '-', t)
    joined = re.sub(r'(10\.\d{4,9}/)\s*\n\s*', r'\1', joined)
    single_line = {_clean_doi(m.group(1)).lower() for m in _DOI.finditer(t)}
    raw = {}
    for m in _DOI.finditer(joined):
        d = _clean_doi(m.group(1))
        raw.setdefault(d.replace("-", "").lower(), []).append(d)
    return raw, single_line


def _check_one(client, store, e, doi, variants, min_title):
    """-> (kind, payload) with kind in ok | bad | mismatch | unchecked, plus retraction notes."""
    for d in variants:
        w = _crossref_work(client, store, d)
        if w.get("status") == "ok":
            res = ("ok", d, None)
            title = w.get("title") or ""
            if title:
                sim = fuzz.partial_ratio(_norm(title), _norm(e["text"]))
                if sim < min_title:
                    res = ("mismatch", d, (title, sim))
            return res, _updates(client, store, d) or []
        if w.get("status") != "not_found":
            return ("unchecked", d, None), []
        ex = _doi_exists(client, store, d)
        if ex is True:
            return ("ok", d, None), []       # registered elsewhere (e.g. DataCite)
        if ex is None:
            return ("unchecked", d, None), []
    return ("bad", variants[0], None), []


@check("ref_doi_online", "DOIs, metadata and retractions (online)", "references", 6,
       "For entries with a DOI: the DOI exists, its title matches the entry, and the work has not been retracted or corrected. "
       "Only the DOIs are sent (to doi.org and api.crossref.org); results are cached.",
       exec_kind="network", default_enabled=True, services=("doi.org", "api.crossref.org"), version=2,
       params={"max_dois": 60, "min_title_match": 70})
def ref_doi_online(doc, ctx):
    import httpx
    from concurrent.futures import ThreadPoolExecutor
    raw, single_line = _raw_dois(doc)
    found = []
    for e in _entries(doc):
        for m in _DOI.finditer(e["text"].replace(" ", "")):
            d = _clean_doi(m.group(1))
            variants = list(dict.fromkeys(raw.get(d.replace("-", "").lower(), []) + [d]))
            found.append((e, d, variants))
            break
    if not found:
        return []
    out_bad, out_bad_maybe, out_mismatch, out_retracted, out_unchecked = [], [], [], [], []
    with httpx.Client(timeout=12, follow_redirects=True) as client, ThreadPoolExecutor(1) as pool:
        jobs = [(e, d, pool.submit(_check_one, client, ctx.store, e, d, v, ctx.params["min_title_match"]))
                for e, d, v in found[: int(ctx.params["max_dois"])]]
        for e, d, fut in jobs:
            (kind, used, extra), notes = fut.result()
            if kind == "bad":
                # A DOI printed on one line that does not exist is confirmed wrong;
                # one split across lines may just be mangled by text extraction.
                (out_bad if used.lower() in single_line else out_bad_maybe).append((e, used))
            elif kind == "mismatch":
                out_mismatch.append((e, used, *extra))
            elif kind == "unchecked":
                out_unchecked.append((e, used))
            for n in notes:
                if n["type"].lower() in ("retraction", "removal", "withdrawal", "expression_of_concern", "correction", "erratum"):
                    out_retracted.append((e, used, n))
    out = []
    page = doc.get("ref_page")
    if out_bad_maybe:
        out.append(Finding("ref_doi_online", "DOI not found (possibly split across lines)", "possible", "low",
                           f"{len(out_bad_maybe)} DOI(s) could not be found; they are broken across lines in the PDF, "
                           "so the text extraction may have changed them.",
                           [ev(page, f"[{e['n']}] {doi}", "doi.org") for e, doi in out_bad_maybe[:10]], 0.4,
                           limitations="Check the DOI as printed in the PDF before concluding anything."))
    page = doc.get("ref_page")
    if out_bad:
        out.append(Finding("ref_doi_online", "DOI does not exist", "issue", "medium",
                           f"{len(out_bad)} DOI(s) are not registered anywhere (confirmed incorrect).",
                           [ev(page, f"[{e['n']}] {doi}", "doi.org") for e, doi in out_bad[:10]], 0.9,
                           suggested_action="Often a typo; many invented references have made-up DOIs."))
    if out_mismatch:
        out.append(Finding("ref_doi_online", "DOI belongs to a different paper", "issue", "medium",
                           f"{len(out_mismatch)} DOI(s) resolve to a work whose title does not match the entry.",
                           [ev(page, f"[{e['n']}] {e['text'][:90]} → DOI {doi} is “{t[:90]}” ({s:.0f}%)", "crossref")
                            for e, doi, t, s in out_mismatch[:10]], 0.75,
                           suggested_action="A real DOI attached to an unrelated title is a known sign of fabricated references."))
    if out_retracted:
        serious = [x for x in out_retracted if x[2]["type"].lower() in ("retraction", "removal", "withdrawal", "expression_of_concern")]
        out.append(Finding("ref_doi_online", "Cited work retracted or corrected" if serious else "Cited work has a correction",
                           "issue" if serious else "possible", "medium" if serious else "low",
                           "Crossref (incl. Retraction Watch) lists notices for these cited works.",
                           [ev(page, f"[{e['n']}] {doi}: {n['type']} (notice {n['notice']})", "crossref") for e, doi, n in out_retracted[:10]], 0.9,
                           suggested_action="Citing a retracted paper is not misconduct by itself; check whether the paper relies on it."))
    if out_unchecked:
        out.append(Finding("ref_doi_online", "Some DOIs could not be checked", "info", "info",
                           f"{len(out_unchecked)} lookup(s) failed (network or service error); not found ≠ wrong.",
                           [ev(page, f"[{e['n']}] {doi}", "crossref") for e, doi in out_unchecked[:5]], 0.3))
    return out
