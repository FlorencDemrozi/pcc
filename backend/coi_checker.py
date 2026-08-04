"""
coi_checker.py — conflict of interest detection.

Three layers per (TPC member × paper) pair:
  1. Email domain matching — exact match on institutional domain
  2. Affiliation matching — synonym dict (exact/prefix only, no fuzzy cross-contamination)
  3. Name matching — full name variants matched against individual parsed author names

Synonym dict is built fresh per request — never mutated globally.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from rapidfuzz import fuzz


# ── Built-in institution synonyms ────────────────────────────────────────────
# Maps canonical name (lower) → list of known variants (lower).
# Used for EXACT lookup only — no fuzzy matching against this dict.
BUILTIN_SYNONYMS: dict[str, list[str]] = {
    "politecnico di torino": [
        "polytechnic university of turin", "polytechnic of turin",
        "polito", "politecnico torino", "turin polytechnic",
    ],
    "politecnico di milano": [
        "polytechnic university of milan", "polytechnic of milan",
        "polimi", "milan polytechnic",
    ],
    "massachusetts institute of technology": ["mit", "m.i.t.", "mit cambridge"],
    "eth zurich": [
        "eth zürich", "eidgenossische technische hochschule",
        "swiss federal institute of technology", "ethz",
    ],
    "imperial college london": ["imperial college", "imperial london"],
    "university college london": ["ucl", "ucl london"],
    "tu berlin": [
        "technische universitat berlin", "technical university berlin",
        "technische universität berlin",
    ],
    "tu munich": [
        "technische universitat munchen", "technical university munich",
        "technische universität münchen", "tum",
    ],
    "tu delft": ["delft university of technology", "technische universiteit delft"],
    "kth": ["kth royal institute of technology", "kungliga tekniska hogskolan"],
    "chalmers": ["chalmers university of technology"],
    "epfl": [
        "ecole polytechnique federale de lausanne",
        "école polytechnique fédérale de lausanne",
        "swiss federal institute of technology lausanne",
    ],
    "inria": [
        "institut national de recherche en informatique",
        "national institute for research in digital science",
    ],
    "cnrs": [
        "centre national de la recherche scientifique",
        "national centre for scientific research",
    ],
    "fraunhofer": ["fraunhofer gesellschaft", "fraunhofer institute"],
}


def _build_lookup(extra: dict[str, list[str]] = None) -> dict[str, str]:
    """
    Build a fresh variant→canonical lookup dict for a single request.
    Combines built-in synonyms with any ROR/LLM-expanded extras.
    Never mutates module-level state.
    """
    lookup: dict[str, str] = {}
    combined = dict(BUILTIN_SYNONYMS)
    if extra:
        for canon, variants in extra.items():
            key = canon.lower().strip()
            combined.setdefault(key, [])
            combined[key].extend(v.lower().strip() for v in variants)
    for canon, variants in combined.items():
        lookup[canon] = canon
        for v in variants:
            v = v.lower().strip()
            if v:
                lookup[v] = canon
    return lookup


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class COIResult:
    paper_id: str
    paper_title: str
    reviewer_id: str
    reviewer_name: str
    reviewer_email: str
    conflict_level: str
    conflict_types: list[str]
    evidence: list[str]
    recommendation: str


@dataclass
class COIReport:
    total_pairs: int
    definite: list[COIResult] = field(default_factory=list)
    probable: list[COIResult] = field(default_factory=list)
    possible: list[COIResult] = field(default_factory=list)
    _clean_count: int = 0

    @property
    def clean(self):
        return []

    @property
    def clean_count(self):
        return self._clean_count

    @property
    def definite_count(self): return len(self.definite)
    @property
    def probable_count(self):  return len(self.probable)
    @property
    def possible_count(self):  return len(self.possible)


def report_to_dict(r: COIReport) -> dict:
    def res(items):
        return [{
            "paper_id":       i.paper_id,
            "paper_title":    i.paper_title,
            "reviewer_id":    i.reviewer_id,
            "reviewer_name":  i.reviewer_name,
            "reviewer_email": i.reviewer_email,
            "conflict_level": i.conflict_level,
            "conflict_types": i.conflict_types,
            "evidence":       i.evidence,
            "recommendation": i.recommendation,
        } for i in items]
    return {
        "total_pairs":    r.total_pairs,
        "definite_count": r.definite_count,
        "probable_count": r.probable_count,
        "possible_count": r.possible_count,
        "clean_count":    r.clean_count,
        "definite": res(r.definite),
        "probable": res(r.probable),
        "possible": res(r.possible),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r'[^\w\s]', ' ', s.lower()).strip()


# Generic email domains — not useful for COI detection
_GENERIC_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com",
    "proton.me", "gmx.com", "gmx.net", "web.de", "mail.com",
    "yandex.com", "yandex.ru", "qq.com", "163.com", "126.com",
}


def _extract_domain(email: str) -> Optional[str]:
    m = re.search(r'@([\w.\-]+)', email.lower())
    if not m:
        return None
    domain = m.group(1)
    return None if domain in _GENERIC_DOMAINS else domain


def _canonical(aff: str, lookup: dict[str, str]) -> Optional[str]:
    """
    Map an affiliation string to its canonical name using EXACT lookup only.
    No fuzzy matching against the synonym dict — that causes cross-institution
    false positives (e.g. "Umeå University" → "SRM University").
    """
    if not aff:
        return None
    norm = _norm(aff)
    # Exact match
    if norm in lookup:
        return lookup[norm]
    # Try without punctuation variants
    stripped = re.sub(r'\s+', ' ', norm)
    if stripped in lookup:
        return lookup[stripped]
    return None


def _affiliations_match(aff_tpc: str, aff_author: str,
                        lookup: dict[str, str]) -> tuple[bool, str, str]:
    """
    Compare two affiliation strings.
    Returns (match: bool, level: 'definite'|'probable', reason: str)

    Strategy:
    1. Canonical exact match via synonym dict (most reliable)
    2. Normalised string exact match
    3. High-confidence token sort fuzzy (≥92, same length class)
    No partial ratio — too many false positives with "X Institute of Technology"
    """
    if not aff_tpc or not aff_author:
        return False, "", ""

    norm_tpc    = _norm(aff_tpc)
    norm_author = _norm(aff_author)

    # 1. Canonical match
    canon_tpc    = _canonical(aff_tpc, lookup)
    canon_author = _canonical(aff_author, lookup)
    if canon_tpc and canon_author and canon_tpc == canon_author:
        return True, "definite", f'Same institution: "{aff_tpc}" → "{canon_tpc}"'

    # 2. Normalised exact match
    if norm_tpc == norm_author:
        return True, "definite", f'Exact affiliation match: "{aff_tpc}"'

    # 3. Token sort fuzzy — only if strings are similar length
    # Require ≥92% AND length ratio ≥0.75 to avoid cross-institution matches
    len_ratio = (min(len(norm_tpc), len(norm_author)) /
                 max(len(norm_tpc), len(norm_author), 1))
    if len_ratio >= 0.75:
        score = fuzz.token_sort_ratio(norm_tpc, norm_author)
        if score >= 92:
            return True, "definite", f'Affiliation match ({score:.0f}%): "{aff_tpc}"'
        if score >= 85:
            return True, "probable", f'Probable affiliation match ({score:.0f}%): "{aff_tpc}" ≈ "{aff_author}"'

    return False, "", ""


def _parse_authors_list(authors_raw: str) -> list[str]:
    if not authors_raw:
        return []
    text = re.sub(r'\s+and\s+', ', ', authors_raw, flags=re.IGNORECASE)
    parts = re.split(r'[,;]+', text)
    return [re.sub(r'[\(\[].+?[\)\]]', '', p).strip() for p in parts if len(p.strip()) > 1]


def _name_variants(full_name: str) -> list[str]:
    if not full_name:
        return []
    parts = full_name.strip().split()
    norm = full_name.strip().lower()
    variants = [norm]
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        variants += [
            f"{first[0].lower()}. {last.lower()}",
            f"{first[0].lower()} {last.lower()}",
            f"{last.lower()} {first.lower()}",
        ]
        if len(last) >= 8:          # only distinctive surnames
            variants.append(last.lower())
        if len(parts) == 3:
            mid = parts[1]
            variants += [
                f"{first[0].lower()}. {mid[0].lower()}. {last.lower()}",
                f"{first[0].lower()} {mid[0].lower()} {last.lower()}",
            ]
    return list(set(variants))


def _names_conflict(tpc_name: str, author_name: str) -> tuple[bool, str]:
    """Returns (matched, confidence) where confidence is 'definite' or 'possible'."""
    if not tpc_name or not author_name:
        return False, ""
    tpc_parts    = tpc_name.strip().split()
    author_parts = author_name.strip().split()
    tpc_norm    = _norm(tpc_name)
    author_norm = _norm(author_name)
    # Full name exact
    if tpc_norm == author_norm:
        return True, "definite"
    # High-confidence fuzzy
    if fuzz.token_sort_ratio(tpc_norm, author_norm) >= 88:
        return True, "definite"
    # Variant intersection
    tpc_v    = set(_name_variants(tpc_name))
    author_v = set(_name_variants(author_name))
    shared   = tpc_v & author_v
    if shared:
        is_initial = any(re.match(r'^[a-z]\.?\s+\w+$', v) for v in shared)
        if is_initial:
            if tpc_parts and author_parts and tpc_parts[0][0].lower() == author_parts[0][0].lower():
                return True, "possible"
            return False, ""
        return True, "definite"
    return False, ""


def _name_in_authors(tpc_name: str, author_names: list[str]) -> tuple[bool, str, str]:
    """Returns (matched, matched_author, confidence)."""
    for author in author_names:
        matched, conf = _names_conflict(tpc_name, author)
        if matched:
            return True, author, conf
    return False, "", ""


def _get_field(row: dict, *keys) -> str:
    for k in keys:
        for c in [k, k.lower(), k.upper(), k.title()]:
            v = row.get(c, "")
            if v:
                return str(v).strip()
    return ""


# ── Main check ────────────────────────────────────────────────────────────────

def check_coi(
    submission_rows: list[dict],
    tpc_rows: list[dict],
    author_rows: list[dict] = None,
    assignment_rows: list[dict] = None,
    extra_synonyms: dict[str, list[str]] = None,
    fuzzy_threshold: int = 75,
) -> COIReport:
    """
    Check TPC members against papers for conflicts.

    Track-aware: if a TPC member has a track assignment, only check them
    against papers in that track. This reduces pairs from N×M to roughly
    (N/tracks) × (M/tracks) per track — typically 100× fewer checks.

    Builds a fresh per-request synonym lookup — never mutates global state.
    """
    # Build per-request synonym lookup
    lookup = _build_lookup(extra_synonyms)

    # Build paper track index: paper_id → track
    paper_track: dict[str, str] = {}
    for row in submission_rows:
        pid   = _get_field(row, "#", "paper_id", "id")
        track = _get_field(row, "track", "Track")
        if pid:
            paper_track[pid] = track

    # Build author index: paper_id → list of {name, email, affiliation}
    author_index: dict[str, list[dict]] = {}

    if author_rows:
        for row in author_rows:
            pid = str(row.get("paper_id") or row.get("#") or "").strip()
            if not pid:
                continue
            if pid not in author_index:
                author_index[pid] = []
            author_index[pid].append({
                "name":        str(row.get("name") or row.get("author") or "").strip(),
                "email":       str(row.get("email") or row.get("Email") or "").strip(),
                "affiliation": str(row.get("affiliation") or row.get("Affiliation") or "").strip(),
            })
    else:
        for row in submission_rows:
            pid = _get_field(row, "#", "paper_id", "id") or "?"
            authors_raw = _get_field(row, "authors", "Authors")
            if pid not in author_index:
                author_index[pid] = []
            for name in _parse_authors_list(authors_raw):
                author_index[pid].append({"name": name, "email": "", "affiliation": ""})

    # Count actual pairs checked (after track filtering)
    actual_pairs = 0
    for tpc in tpc_rows:
        tpc_track = _get_field(tpc, "track", "Track")
        if tpc_track:
            actual_pairs += sum(1 for p in submission_rows
                                if paper_track.get(_get_field(p,"#","paper_id","id") or "") == tpc_track)
        else:
            actual_pairs += len(submission_rows)

    report = COIReport(total_pairs=actual_pairs)

    for paper in submission_rows:
        paper_id    = _get_field(paper, "#", "paper_id", "id") or "?"
        paper_title = _get_field(paper, "title", "Title") or f"Paper #{paper_id}"
        paper_track_val = paper_track.get(paper_id, "")
        authors_raw = _get_field(paper, "authors", "Authors")

        paper_authors = author_index.get(paper_id, [])
        author_names  = [a["name"] for a in paper_authors if a.get("name")]
        author_emails = [a["email"] for a in paper_authors if a.get("email")]
        author_affs   = [a["affiliation"] for a in paper_authors if a.get("affiliation")]

        # Pre-compute canonical affiliations for paper authors
        paper_canonicals = {
            _canonical(aff, lookup)
            for aff in author_affs
            if _canonical(aff, lookup)
        }

        author_domains = {
            _extract_domain(e)
            for e in author_emails
            if _extract_domain(e)
        }

        for tpc in tpc_rows:
            tpc_name  = _get_field(tpc, "name", "Name", "full_name")
            tpc_email = _get_field(tpc, "email", "Email", "e-mail")
            tpc_aff   = _get_field(tpc, "affiliation", "Affiliation",
                                   "Affiliaiton", "institution")
            tpc_role  = _get_field(tpc, "role", "Role")
            tpc_track = _get_field(tpc, "track", "Track")

            # ── Track filter ───────────────────────────────────────────────
            # If the TPC member has a track assignment AND the paper has a track,
            # only check when they match. Skip cross-track pairs entirely.
            if tpc_track and paper_track_val and tpc_track != paper_track_val:
                report._clean_count += 1
                continue

            conflict_types: list[str] = []
            evidence: list[str] = []
            level = "None"

            # ── Layer 1: Email domain ──────────────────────────────────────
            tpc_domain = _extract_domain(tpc_email)
            if tpc_domain and tpc_domain in author_domains:
                matching = [e for e in author_emails if _extract_domain(e) == tpc_domain]
                conflict_types.append("Email domain")
                evidence.append(
                    f'Shared domain "@{tpc_domain}"'
                    f' (author: {matching[0] if matching else "?"})'
                )
                level = "Definite"

            # ── Layer 2: Affiliation ───────────────────────────────────────
            if tpc_aff and author_affs:
                for aff_author in author_affs:
                    matched, aff_level, reason = _affiliations_match(
                        tpc_aff, aff_author, lookup
                    )
                    if matched:
                        conflict_types.append("Affiliation match")
                        evidence.append(reason)
                        if aff_level == "definite" and level != "Definite":
                            level = "Definite"
                        elif aff_level == "probable" and level == "None":
                            level = "Probable"
                        break

            # ── Layer 3: Name match ────────────────────────────────────────
            if tpc_name:
                names_to_check = (author_names if author_names
                                  else _parse_authors_list(authors_raw))
                matched, matched_author, conf = _name_in_authors(tpc_name, names_to_check)
                if matched:
                    conflict_types.append("Name match")
                    if conf == "possible":
                        evidence.append(
                            f'Possible name match: "{tpc_name}" ≈ "{matched_author}" (ambiguous initial)'
                        )
                        if level == "None":
                            level = "Possible"
                    else:
                        evidence.append(f'Name match: "{tpc_name}" = "{matched_author}"')
                        level = "Definite"

            if level == "None":
                report._clean_count += 1
                continue

            rec = {
                "Definite": "Do not assign to this paper",
                "Probable": "Flag for chair review before assigning",
                "Possible": "Verify manually before assigning",
            }.get(level, "No action needed")

            display_name = f"{tpc_name} ({tpc_role})" if tpc_role else tpc_name

            result = COIResult(
                paper_id=paper_id,
                paper_title=paper_title,
                reviewer_id=tpc_email or tpc_name,
                reviewer_name=display_name,
                reviewer_email=tpc_email,
                conflict_level=level,
                conflict_types=conflict_types,
                evidence=evidence,
                recommendation=rec,
            )
            getattr(report, level.lower()).append(result)

    return report


async def check_coi_async(
    submission_rows: list[dict],
    tpc_rows: list[dict],
    author_rows: list[dict] = None,
    extra_synonyms: dict[str, list[str]] = None,
    fuzzy_threshold: int = 75,
    use_ror: bool = True,
    use_llm: bool = True,
) -> COIReport:
    """
    Async version with optional ROR + LLM affiliation synonym expansion.
    Expansions are collected into a per-request dict, never mutating global state.
    """
    from affiliation_expander import expand_affiliations

    # Collect all unique affiliations
    aff_keys = ["affiliation", "Affiliation", "Affiliaiton", "institution"]
    all_affs = []
    for row in tpc_rows + (author_rows or []):
        for k in aff_keys:
            val = str(row.get(k) or "").strip()
            if len(val) > 3:
                all_affs.append(val)

    # Expand via ROR + LLM — returns a plain dict, does NOT touch globals
    expanded: dict[str, list[str]] = {}
    if all_affs and (use_ror or use_llm):
        try:
            expanded = await expand_affiliations(
                all_affs, use_ror=use_ror, use_llm=use_llm
            )
        except Exception:
            pass

    # Merge user-provided extras into expanded (still per-request only)
    if extra_synonyms:
        for canon, variants in extra_synonyms.items():
            key = canon.lower().strip()
            expanded.setdefault(key, [])
            expanded[key].extend(v.lower().strip() for v in variants)

    return check_coi(
        submission_rows=submission_rows,
        tpc_rows=tpc_rows,
        author_rows=author_rows,
        extra_synonyms=expanded,
        fuzzy_threshold=fuzzy_threshold,
    )
