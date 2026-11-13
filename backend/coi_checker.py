"""
coi_checker.py — conflict of interest detection.

Three layers per (TPC member × paper) pair:
  1. Email domain matching — registrable institutional domain (cs.mit.edu ~ mit.edu)
  2. Affiliation matching — synonym dict + institution-segment comparison (campus-aware)
  3. Name matching — full name variants matched against individual parsed author names

Synonym dict is built fresh per request — never mutated globally.
"""

import re
import unicodedata
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
    Every key (canonical and variant) goes through the same _norm()/_norm_aff()
    used at lookup time, so "M.I.T." and punctuated ROR labels match.
    Never mutates module-level state.
    """
    lookup: dict[str, str] = {}
    combined: dict[str, list[str]] = {}
    for canon, variants in BUILTIN_SYNONYMS.items():
        combined.setdefault(_norm(canon), []).extend(variants)
    if extra:
        for canon, variants in extra.items():
            key = _norm(canon)
            if not key:
                continue
            combined.setdefault(key, [])
            if isinstance(variants, str):
                variants = [variants]
            combined[key].extend(str(v) for v in (variants or []) if v)
    for canon, variants in combined.items():
        for k in (canon, _norm_aff(canon)):
            lookup.setdefault(k, canon)
        for v in variants:
            for k in (_norm(v), _norm_aff(v)):
                if k:
                    lookup.setdefault(k, canon)
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
    skipped_pairs: int = 0     # cross-track pairs not checked

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
        "skipped_pairs":  r.skipped_pairs,
        "definite": res(r.definite),
        "probable": res(r.probable),
        "possible": res(r.possible),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

_ACRONYM_RE = re.compile(r'\b(?:[A-Za-z]\.){2,}')


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _norm(s: str) -> str:
    """Canonical normalisation used for EVERY synonym key and lookup.

    Lower-cases, strips accents, collapses dotted acronyms ("M.I.T." → "mit"),
    turns remaining punctuation into spaces and collapses whitespace.
    """
    if not s:
        return ""
    s = _strip_accents(str(s)).lower()
    s = _ACRONYM_RE.sub(lambda m: m.group(0).replace(".", ""), s)
    s = s.replace("&", " and ")
    s = re.sub(r'[^\w\s]', ' ', s)
    s = s.replace("_", " ")
    return re.sub(r'\s+', ' ', s).strip()


# ── Email domains ─────────────────────────────────────────────────────────────

# Generic / webmail / professional-society domains — not useful for COI
# detection (compared on the registrable domain).
_GENERIC_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com",
    "hotmail.com", "outlook.com", "live.com", "msn.com", "passport.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "protonmail.ch",
    "proton.me", "pm.me", "gmx.com", "gmx.net", "gmx.de", "web.de", "t-online.de",
    "mail.com", "email.com", "yandex.com", "yandex.ru", "mail.ru", "inbox.ru",
    "bk.ru", "list.ru", "rambler.ru", "qq.com", "foxmail.com", "163.com",
    "126.com", "yeah.net", "sina.com", "sina.cn", "sohu.com", "aliyun.com",
    "naver.com", "daum.net", "hanmail.net", "rediffmail.com", "zoho.com",
    "tutanota.com", "tuta.io", "fastmail.com", "hey.com", "libero.it",
    "virgilio.it", "tiscali.it", "orange.fr", "free.fr", "laposte.net",
    "wanadoo.fr", "sfr.fr", "btinternet.com", "seznam.cz", "wp.pl", "o2.pl",
    "interia.pl", "onet.pl", "uol.com.br", "bol.com.br", "terra.com.br",
    "ieee.org", "acm.org", "computer.org", "siam.org", "ams.org", "iet.org",
    "alum.mit.edu", "alumni.stanford.edu",
}
# First label of the registrable domain that marks a webmail provider in
# any country (yahoo.co.uk, hotmail.fr, outlook.de, live.co.uk, gmx.at, ...).
_GENERIC_LABELS = {
    "gmail", "googlemail", "yahoo", "ymail", "hotmail", "outlook", "live",
    "msn", "gmx", "yandex", "protonmail", "proton", "aol", "icloud", "zoho",
    "mail", "email", "inbox", "rediffmail",
}
# Two-label public suffixes (no external dependency; covers academia well).
_TWO_PART_SUFFIXES = {
    "ac.uk", "co.uk", "org.uk", "gov.uk", "nhs.uk", "ltd.uk", "plc.uk", "me.uk",
    "edu.au", "com.au", "org.au", "gov.au", "net.au",
    "ac.jp", "co.jp", "or.jp", "go.jp", "ne.jp",
    "edu.cn", "com.cn", "ac.cn", "org.cn", "gov.cn", "net.cn",
    "com.br", "edu.br", "org.br", "gov.br", "net.br",
    "ac.in", "edu.in", "co.in", "res.in", "ernet.in", "org.in", "gov.in",
    "ac.kr", "co.kr", "re.kr", "or.kr", "go.kr",
    "ac.nz", "co.nz", "org.nz", "govt.nz",
    "edu.sg", "com.sg", "gov.sg", "org.sg",
    "edu.hk", "com.hk", "org.hk", "gov.hk",
    "edu.tw", "com.tw", "org.tw", "gov.tw",
    "ac.za", "co.za", "org.za", "gov.za",
    "edu.tr", "com.tr", "org.tr", "gov.tr",
    "ac.il", "co.il", "org.il", "gov.il",
    "ac.ir", "ac.th", "co.th", "ac.id", "co.id", "edu.my", "com.my",
    "edu.pk", "com.pk", "edu.eg", "edu.sa", "com.sa", "edu.mx", "com.mx",
    "edu.ar", "com.ar", "edu.co", "com.co", "edu.pe", "edu.pl", "com.pl",
    "ac.at", "co.at", "ac.be", "ac.cy", "ac.ma", "ac.rs", "edu.vn", "edu.ph",
    "edu.qa", "edu.lb", "edu.jo", "edu.ng", "edu.gh", "ac.ke",
    "edu.es", "com.es", "edu.it", "edu.gr", "edu.pt", "edu.ru", "msk.ru", "spb.ru",
}


def _registrable_domain(domain: str) -> str:
    labels = [l for l in domain.lower().strip(".").split(".") if l]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _TWO_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _is_generic_domain(domain: str) -> bool:
    d = domain.lower()
    if d in _GENERIC_DOMAINS:
        return True
    reg = _registrable_domain(d)
    if reg in _GENERIC_DOMAINS:
        return True
    first = reg.split(".")[0] if reg else ""
    return first in _GENERIC_LABELS


def _extract_domain(email: str) -> Optional[str]:
    """Return the registrable domain of an e-mail address (cs.mit.edu → mit.edu),
    or None for generic / webmail / professional-society addresses."""
    m = re.search(r'@([\w.\-]+)', (email or "").lower())
    if not m:
        return None
    domain = m.group(1).strip(".")
    if not domain or "." not in domain or _is_generic_domain(domain):
        return None
    return _registrable_domain(domain)


# ── Affiliations ──────────────────────────────────────────────────────────────

_ABBREV = [
    (r'\buniv\b', 'university'), (r'\buni\b', 'university'),
    (r'\bu of\b', 'university of'), (r'\binst\b', 'institute'),
    (r'\btech\b', 'technology'), (r'\bnatl\b', 'national'),
    (r'\bdept\b', 'department'), (r'\bdep\b', 'department'),
    (r'\bsci\b', 'science'), (r'\bcoll\b', 'college'),
]

# Words that mark an institution-level segment
_INSTITUTION_WORDS = re.compile(
    r'\b(universit\w*|universidad|universidade|universita|universite|'
    r'universiteit|universitet\w*|uniwersytet|institut\w*|college|polytechn\w*|'
    r'politecnic\w*|politechnika|polytechnique|hochschule|ecole|academy|akademie|'
    r'academia|tecnologico|technion|kth|eth|epfl|mit|inria|cnrs|fraunhofer|'
    r'max planck|csiro|nasa|cern|riken|a star|corporation|corp|inc|ltd|gmbh|'
    r'labs|research)\b'
)
# Segments that are sub-units of an institution (department, lab, faculty...)
_SUBUNIT_PREFIX = re.compile(
    r'^(department|dept|dep|faculty|division|chair|group|lab|laboratory|'
    r'laboratoire|labo|centre|center|unit|section|program|programme|'
    r'school of|graduate school|research group|ece|cs|eecs|cse)\b'
)

# Tokens ignored when looking for distinguishing tokens between affiliations
_GENERIC_AFF_TOKENS = {
    "university", "universitat", "universitaet", "universite", "universidad",
    "universidade", "universita", "universiteit", "universitet", "of", "the",
    "at", "de", "di", "du", "der", "des", "la", "le", "del", "della", "delle",
    "degli", "and", "for", "in", "fur", "zu", "y", "e", "et",
}
_COUNTRIES = {
    "norway", "sweden", "denmark", "finland", "iceland", "germany", "france",
    "italy", "spain", "portugal", "netherlands", "belgium", "switzerland",
    "austria", "uk", "united", "kingdom", "england", "scotland", "wales",
    "ireland", "usa", "us", "states", "america", "canada", "mexico", "brazil",
    "argentina", "chile", "china", "pr", "prc", "japan", "korea", "south",
    "india", "pakistan", "australia", "zealand", "new", "singapore", "malaysia",
    "taiwan", "hong", "kong", "israel", "turkey", "greece", "poland", "czech",
    "republic", "hungary", "romania", "russia", "iran", "egypt", "saudi",
    "arabia", "uae", "emirates", "qatar", "luxembourg", "estonia", "latvia",
    "lithuania", "slovenia", "croatia", "serbia", "cyprus", "malta", "vietnam",
    "thailand", "indonesia", "philippines", "nigeria", "kenya", "africa",
}


def _norm_aff(s: str) -> str:
    s = _norm(s)
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s)
    return re.sub(r'\s+', ' ', s).strip()


def _institution_parts(aff: str) -> tuple[str, str]:
    """Split an affiliation into (institution segment, qualifier).

    "Dept. of CS, University of Stavanger, Norway" → ("university of stavanger", "")
    "University of California, Davis"              → ("university of california", "davis")
    The qualifier is the short segment right after the institution (campus /
    city), ignored when it is a country or already part of the institution.
    """
    raw_segs = [s for s in re.split(r'[,;\n|]+', aff or "") if s.strip()]
    segs = [_norm_aff(s) for s in raw_segs]
    segs = [s for s in segs if s]
    if not segs:
        return "", ""
    idx = None
    for i, s in enumerate(segs):
        if _INSTITUTION_WORDS.search(s) and not _SUBUNIT_PREFIX.match(s):
            idx = i
            break
    if idx is None:
        # fall back: first segment that is not obviously a sub-unit
        for i, s in enumerate(segs):
            if not _SUBUNIT_PREFIX.match(s):
                idx = i
                break
    if idx is None:
        idx = len(segs) - 1
    inst = segs[idx]
    qual = ""
    if idx + 1 < len(segs):
        nxt = segs[idx + 1]
        toks = nxt.split()
        inst_toks = set(inst.split())
        if (len(toks) <= 3 and not _INSTITUTION_WORDS.search(nxt)
                and not all(t in _COUNTRIES or t in inst_toks for t in toks)
                and not re.search(r'\d', nxt)):
            qual = nxt
    return inst, qual


def institution_segment(aff: str) -> str:
    """Public helper: the institution-level part of an affiliation string."""
    return _institution_parts(aff)[0]


def _canonical(aff: str, lookup: dict[str, str]) -> Optional[str]:
    """
    Map an affiliation string to its canonical name using EXACT lookup only
    (on the full normalised string, then on its institution segment).
    No fuzzy matching against the synonym dict — that causes cross-institution
    false positives (e.g. "Umeå University" → "SRM University").
    """
    if not aff:
        return None
    for key in (_norm(aff), _norm_aff(aff), institution_segment(aff)):
        if key and key in lookup:
            return lookup[key]
    return None


def _distinguishing(a: str, b: str) -> tuple[set, set]:
    ta = {t for t in a.split() if t not in _GENERIC_AFF_TOKENS and t not in _COUNTRIES}
    tb = {t for t in b.split() if t not in _GENERIC_AFF_TOKENS and t not in _COUNTRIES}
    only_a, only_b = ta - tb, tb - ta
    # tolerate typos: a token only in A that closely matches a token only in B
    for x in list(only_a):
        for y in list(only_b):
            if len(x) >= 4 and len(y) >= 4 and fuzz.ratio(x, y) >= 85:
                only_a.discard(x)
                only_b.discard(y)
                break
    # ...or a misspelt generic word ("univeristy")
    long_generic = [g for g in _GENERIC_AFF_TOKENS if len(g) >= 6]
    for side in (only_a, only_b):
        for x in list(side):
            if len(x) >= 6 and any(fuzz.ratio(x, g) >= 85 for g in long_generic):
                side.discard(x)
    return only_a, only_b


def _affiliations_match(aff_tpc: str, aff_author: str,
                        lookup: dict[str, str]) -> tuple[bool, str, str]:
    """
    Compare two affiliation strings.
    Returns (match: bool, level: 'definite'|'probable', reason: str)

    Strategy:
    1. Canonical exact match via synonym dict (full string or institution segment)
    2. Institution-segment exact match (department / lab prefixes stripped)
    3. Token-sort fuzzy on institution segments, only when no distinguishing
       tokens differ (campus/city names like "Davis" vs "Irvine" → mismatch)
    A differing campus qualifier ("University of California, Davis" vs
    ", Irvine") is always a mismatch.
    """
    if not aff_tpc or not aff_author:
        return False, "", ""

    inst_t, qual_t = _institution_parts(aff_tpc)
    inst_a, qual_a = _institution_parts(aff_author)
    if not inst_t or not inst_a:
        return False, "", ""

    def _qual_level(base: str) -> Optional[str]:
        if qual_t and qual_a:
            if qual_t == qual_a or fuzz.ratio(qual_t, qual_a) >= 90:
                return base
            return None                     # different campus
        if qual_t or qual_a:
            return "probable"               # campus known on one side only
        return base

    # Explicitly different campuses ("University of California, Davis" vs
    # ", Irvine") never match — not even through a synonym/ROR canonical,
    # which may map both to the parent system.
    if qual_t and qual_a and _qual_level("definite") is None:
        return False, "", ""

    # 1. Canonical match (synonym dict / ROR / LLM)
    canon_tpc    = _canonical(aff_tpc, lookup)
    canon_author = _canonical(aff_author, lookup)
    if canon_tpc and canon_author and canon_tpc == canon_author:
        return True, "definite", f'Same institution: "{aff_tpc}" → "{canon_tpc}"'

    # 2. Institution segment exact match
    if inst_t == inst_a:
        lvl = _qual_level("definite")
        if lvl:
            return True, lvl, f'Affiliation match: "{aff_tpc}" ≈ "{aff_author}"'
        return False, "", ""

    # 3. Fuzzy on institution segments
    len_ratio = min(len(inst_t), len(inst_a)) / max(len(inst_t), len(inst_a), 1)
    if len_ratio >= 0.75 and min(len(inst_t), len(inst_a)) >= 8:
        only_t, only_a = _distinguishing(inst_t, inst_a)
        if only_t or only_a:
            return False, "", ""
        score = fuzz.token_sort_ratio(inst_t, inst_a)
        if score >= 92:
            lvl = _qual_level("definite")
        elif score >= 85:
            lvl = _qual_level("probable")
        else:
            lvl = None
        if lvl:
            return True, lvl, f'Affiliation match ({score:.0f}%): "{aff_tpc}" ≈ "{aff_author}"'

    return False, "", ""


# ── Names ─────────────────────────────────────────────────────────────────────

def _parse_authors_list(authors_raw: str) -> list[str]:
    if not authors_raw:
        return []
    text = re.sub(r'\s+and\s+', ', ', authors_raw, flags=re.IGNORECASE)
    parts = re.split(r'[,;]+', text)
    return [re.sub(r'[\(\[].+?[\)\]]', '', p).strip() for p in parts if len(p.strip()) > 1]


def _name_tokens(name: str) -> list[str]:
    """Normalised name tokens in 'first ... last' order ("Smith, John" handled)."""
    if not name:
        return []
    name = re.sub(r'[\(\[].*?[\)\]]', ' ', str(name))
    if name.count(",") == 1:
        last, first = name.split(",")
        if first.strip() and last.strip():
            name = f"{first} {last}"
    name = _strip_accents(name).lower()
    return re.findall(r"[a-z]+", name)


def _name_variants(full_name: str) -> list[str]:
    """Initial-based variants of a name. No bare-surname variant (a shared
    surname alone is never evidence of identity)."""
    toks = _name_tokens(full_name)
    if not toks:
        return []
    variants = [" ".join(toks)]
    if len(toks) >= 2:
        first, last = toks[0], toks[-1]
        variants += [f"{first[0]}. {last}", f"{first[0]} {last}", f"{last} {first}"]
        if len(toks) == 3:
            mid = toks[1]
            variants += [f"{first[0]}. {mid[0]}. {last}", f"{first[0]} {mid[0]} {last}"]
    return list(set(variants))


def _given_compatible(a: list[str], b: list[str]) -> Optional[str]:
    """Compare given-name token lists. Returns 'exact', 'initial' or None."""
    if not a or not b:
        return None
    fa, fb = a[0], b[0]
    if fa == fb:
        kind = "exact"
    elif (len(fa) == 1 and fb.startswith(fa)) or (len(fb) == 1 and fa.startswith(fb)):
        kind = "initial"
    else:
        return None
    # Middle names/initials, where both sides have them, must be compatible
    for x, y in zip(a[1:], b[1:]):
        if not (x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))):
            return None
    return kind


def _names_conflict(tpc_name: str, author_name: str) -> tuple[bool, str]:
    """Returns (matched, confidence) where confidence is 'definite' or 'possible'.

    Definite: identical surname token AND first name identical or
              initial-compatible ("J. Smith" ~ "John Smith").
    Possible: fuzzy-only similarity (high threshold, long names), or same
              tokens in a different order.
    A shared surname with a different first name is NOT a match.
    """
    ta, tb = _name_tokens(tpc_name), _name_tokens(author_name)
    if not ta or not tb:
        return False, ""
    if ta == tb:
        return True, "definite"
    if len(ta) < 2 or len(tb) < 2:
        return False, ""

    if ta[-1] == tb[-1]:
        kind = _given_compatible(ta[:-1], tb[:-1])
        if kind:
            return True, "definite"
        # first names differ but are very close (Jon/John, transliteration)
        if (len(ta[0]) >= 3 and len(tb[0]) >= 3
                and fuzz.ratio(ta[0], tb[0]) >= 85):
            return True, "possible"
        return False, ""

    # Same tokens, different order (e.g. "Li Jian" vs "Jian Li")
    if sorted(ta) == sorted(tb):
        return True, "possible"

    # Fuzzy-only: high threshold + minimum length + same first name
    a_s, b_s = " ".join(ta), " ".join(tb)
    if (min(len(a_s), len(b_s)) >= 12 and ta[0] == tb[0]
            and len(ta[-1]) >= 5 and len(tb[-1]) >= 5
            and fuzz.ratio(ta[-1], tb[-1]) >= 90
            and fuzz.token_sort_ratio(a_s, b_s) >= 95):
        return True, "possible"
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

    # total_pairs is counted inside the loop so it always equals
    # definite + probable + possible + clean (cross-track pairs are skipped
    # and reported separately as skipped_pairs).
    report = COIReport(total_pairs=0)

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
                report.skipped_pairs += 1
                continue
            report.total_pairs += 1

            conflict_types: list[str] = []
            evidence: list[str] = []
            level = "None"

            # ── Layer 0: TPC member is an author (same e-mail address) ─────
            if tpc_email and tpc_email.strip().lower() in {e.strip().lower() for e in author_emails}:
                conflict_types.append("Author")
                evidence.append(f'TPC member e-mail "{tpc_email}" is an author e-mail')
                level = "Definite"

            # ── Layer 1: Email domain (registrable domain) ─────────────────
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
    use_ror: bool = False,
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
            key = _norm(canon)
            if not key:
                continue
            if isinstance(variants, str):
                variants = [variants]
            expanded.setdefault(key, [])
            expanded[key].extend(str(v) for v in (variants or []) if v)

    return check_coi(
        submission_rows=submission_rows,
        tpc_rows=tpc_rows,
        author_rows=author_rows,
        extra_synonyms=expanded,
        fuzzy_threshold=fuzzy_threshold,
    )
