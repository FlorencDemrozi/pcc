"""Section 3 -- anonymity (double-blind calls only).

Every result says whether it is a clear violation (outcome "issue") or only
a possible clue (outcome "possible").
"""

import re
import unicodedata

from .registry import check
from .findings import Finding, ev
from . import docmodel


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


@check("author_names", "Author names in the paper", "anonymity", 3,
       "Names of the submitting authors (from the submission system) in the body text or in the PDF properties. "
       "Names inside the reference list are not counted (third-person self-citation is allowed).",
       needs_double_blind=True)
def author_names(doc, ctx):
    names = [n for n in (ctx.paper.get("authors") or []) if n and len(n.split()) >= 2]
    out = []
    md_author = (doc.get("metadata") or {}).get("author", "")
    if md_author.strip():
        hit = [n for n in names if _fold(n.split()[-1]) in _fold(md_author)]
        out.append(Finding("author_names", "Author in the PDF properties" if hit else "Name in the PDF properties",
                           "issue" if hit else "possible", "high" if hit else "low",
                           "The PDF 'Author' field is filled in" + (" with a submitting author's name." if hit else "; check whether it identifies the authors."),
                           [ev(None, md_author, "pdf-metadata")], 0.95 if hit else 0.5,
                           suggested_action="Ask the authors to clear the PDF properties."))
    if not names:
        return out
    body = docmodel.body_text(doc)
    fb = _fold(body)
    for n in names:
        parts = n.split()
        first, last = _fold(parts[0]), _fold(parts[-1])
        if len(last) < 3:
            continue
        pats = [re.escape(first) + r'\s+(?:\w\.\s*)?' + re.escape(last),
                re.escape(first[0]) + r'\.\s*(?:\w\.\s*)?' + re.escape(last)]
        for pat in pats:
            m = re.search(r'\b' + pat + r'\b', fb)
            if m:
                page = next((i + 1 for i, t in enumerate(doc["page_texts"])
                             if re.search(r'\b' + pat + r'\b', _fold(t))), None)
                out.append(Finding("author_names", "Author name in the paper", "issue", "high",
                                   f"“{n}”, a submitting author, appears in the text (outside the references).",
                                   [ev(page, docmodel.snippet(fb, m.start(), m.end()))], 0.9,
                                   suggested_action="Clear violation if it is the author block or a first-person mention; "
                                                    "check the context before deciding."))
                break
    return out


_ACK_HEAD = re.compile(r'(?mi)^\s*(?:[IVX]+\.|\d+\.?)?\s*(acknowledge?ments?|funding)\s*\.?\s*$')
_SUPPORT = re.compile(
    r'(?i)\b(?:this|the present|our)\s+(?:work|research|project|study|paper)\s+(?:was|is|has been)\s+'
    r'(?:\w+\s+){0,2}(?:supported|funded|sponsored|financed)\s+by\b[^.]{0,200}')
_GRANT = re.compile(
    r'(?i)\b(?:grant|contract|project|award)\s*(?:no\.?|number|nr\.?|#|agreement)?\s*[:#]?\s*'
    r'(?=[A-Z0-9/\-]*\d)[A-Z0-9][A-Z0-9/\-]{4,}\b')


@check("acknowledgements", "Acknowledgements and funding", "anonymity", 3,
       "Acknowledgement or funding sections, 'this work was supported by ...' sentences, and grant numbers.",
       needs_double_blind=True)
def acknowledgements(doc, ctx):
    out = []
    for p, t in enumerate(doc["page_texts"], 1):
        m = _ACK_HEAD.search(t)
        if m:
            out.append(Finding("acknowledgements", "Acknowledgement section", "issue", "medium",
                               "Double-blind calls usually ask authors to remove acknowledgements until the camera-ready version.",
                               [ev(p, docmodel.snippet(t, m.start(), m.end() + 200, 10))], 0.85,
                               suggested_action="Check whether it names people, institutions or grants."))
            break
    body = docmodel.body_text(doc)
    for page, ex, m in docmodel.iter_matches(doc, _SUPPORT, text=body, limit=3):
        out.append(Finding("acknowledgements", "Funding statement", "issue", "medium",
                           "A funding statement can identify the authors' institution or group.",
                           [ev(page, ex)], 0.8))
    grants = list(docmodel.iter_matches(doc, _GRANT, text=body, limit=5))
    if grants:
        out.append(Finding("acknowledgements", "Grant or project number", "possible", "medium",
                           "Grant numbers can be looked up and identify the authors.",
                           [ev(p, ex) for p, ex, _ in grants], 0.6,
                           limitations="Also matches part numbers or standards that look like grant IDs."))
    return out


_URL = re.compile(r'(?i)\b(?:https?://|www\.)[^\s<>\]\)\}"\']{4,}')
_ANON_OK = re.compile(r'(?i)anonymous\.4open\.science|anonymous\.|openreview\.net|doi\.org|arxiv\.org/abs|ieee\.org|acm\.org|'
                      r'springer|zenodo\.org/record|figshare|github\.com/anonymous|example\.(?:com|org)')
_IDENT_URL = re.compile(r'(?i)github\.com/[^/\s]+|gitlab\.[^/\s]+/[^/\s]+|bitbucket\.org/[^/\s]+|huggingface\.co/[^/\s]+|'
                        r'sites\.google\.com|/~[a-z]|\.edu/|\.ac\.[a-z]{2}/|\.uni-[^/\s]+|people\.|homepages?\.|'
                        r'researchgate\.net/profile|scholar\.google|orcid\.org/\d|linkedin\.com/in|lab\.|group\.')


@check("identifying_links", "Links that may identify the authors", "anonymity", 3,
       "URLs to personal GitHub/GitLab accounts, lab or university pages, profiles. Anonymised services are ignored.",
       needs_double_blind=True)
def identifying_links(doc, ctx):
    urls = {}
    body = docmodel.body_text(doc)
    for m in _URL.finditer(body):
        urls.setdefault(m.group(0).rstrip('.,;:'), docmodel.find_page(doc, m.group(0)))
    for p in doc["pages"]:
        if doc.get("ref_page") and p["n"] > doc["ref_page"]:
            continue
        for u in p["links"]:
            urls.setdefault(u, p["n"])
    evs = []
    for u, page in urls.items():
        if _ANON_OK.search(u) or u.lower().startswith("mailto:"):
            continue
        if _IDENT_URL.search(u):
            evs.append(ev(page, u, "link"))
    if not evs:
        return []
    return [Finding("identifying_links", "Possibly identifying link(s)", "possible", "medium",
                    "These links may point to the authors' own accounts or pages.", evs[:10], 0.6,
                    limitations="A link to a third-party tool's repository is fine; only the authors' own pages matter.",
                    suggested_action="Open the links; if they reveal the authors it is a violation.")]


_SELF_REF = re.compile(
    r'(?i)\b(?:in\s+)?(?:our|my)\s+(?:previous|prior|earlier|recent|past|own)\s+(?:work|paper|study|studies|publication|research|'
    r'article|approach|method|design|implementation)s?\b[^.]{0,80}|'
    r'\bwe\s+(?:have\s+)?(?:previously|recently|earlier)\s+(?:proposed|presented|introduced|showed|shown|developed|published|reported)\b[^.]{0,80}|'
    r'\b(?:our|my)\s+(?:group|lab|laboratory|team|university|institute|department)\b[^.]{0,60}|'
    r'\bas\s+(?:we|I)\s+(?:showed|described|reported|demonstrated)\s+in\s+\[\d+')


@check("self_reference", "Self-identifying phrasing", "anonymity", 3,
       "Phrases like 'our previous work [12]' or 'our lab' that tie the paper to earlier work by the same authors.",
       needs_double_blind=True)
def self_reference(doc, ctx):
    hits = list(docmodel.iter_matches(doc, _SELF_REF, text=docmodel.body_text(doc), limit=8))
    if not hits:
        return []
    cited = [h for h in hits if re.search(r'\[\d', h[1])]
    return [Finding("self_reference", "Self-identifying phrasing", "possible", "medium" if cited else "low",
                    f"{len(hits)} phrase(s) refer to the authors' own earlier work"
                    + (" together with a citation, which makes the authors identifiable." if cited else "."),
                    [ev(p, ex) for p, ex, _ in hits], 0.6,
                    limitations="Possible clue only; whether it really reveals the authors depends on the cited paper.",
                    suggested_action="Check the cited reference; if it is the authors' own paper, ask them to cite it in the third person.")]
