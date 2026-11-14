"""Section 1 -- file integrity."""

import hashlib
import re

from rapidfuzz import fuzz

from .registry import check
from .findings import Finding, ev
from . import docmodel


@check("file_opens", "PDF opens and has text", "integrity", 1,
       "The file is a PDF, is not encrypted or damaged, and every page could be read.", version=1)
def file_opens(doc, ctx):
    if doc.get("error"):
        return [Finding("file_opens", "PDF cannot be read", "issue", "high", doc["error"],
                        [ev(None, doc["error"], "file")], 1.0,
                        suggested_action="Ask the authors for a readable, unencrypted PDF.")]
    out = []
    bad = [p for p in doc["pages"] if p.get("error")]
    if bad:
        out.append(Finding("file_opens", "Some pages could not be read", "issue", "medium",
                           f"{len(bad)} page(s) raised errors during extraction; the file may be damaged or truncated.",
                           [ev(p["n"], p["error"], "file") for p in bad[:5]], 0.8,
                           suggested_action="Open the PDF and check the listed pages."))
    if doc.get("n_pages", 0) == 0:
        out.append(Finding("file_opens", "PDF has no pages", "issue", "high", "", [ev(None, "0 pages", "file")], 1.0))
    return out


@check("blank_pages", "Blank pages", "integrity", 1,
       "Pages with no text and no images.", params={"min_chars": 20},
       param_help={"min_chars": "A page with fewer characters than this (and no images) counts as blank"})
def blank_pages(doc, ctx):
    lim = int(ctx.params["min_chars"])
    blank = [p for p in doc["pages"] if p["n_chars"] < lim and p["n_images"] == 0 and not p.get("error")]
    if not blank:
        return []
    return [Finding("blank_pages", "Blank page(s)", "issue", "low",
                    f"Page(s) {', '.join(str(p['n']) for p in blank)} contain no text or images.",
                    [ev(p["n"], f"{p['n_chars']} characters, no images", "layout") for p in blank[:10]], 0.9,
                    suggested_action="Check whether content is missing (failed export) or the page is padding.")]


@check("duplicate_pages", "Duplicated pages", "integrity", 1,
       "Two pages with identical text, usually an export or merge error.")
def duplicate_pages(doc, ctx):
    seen, dups = {}, []
    for i, t in enumerate(doc["page_texts"]):
        norm = " ".join(t.split())
        if len(norm) < 200:
            continue
        h = hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()
        if h in seen:
            dups.append((seen[h], i + 1, norm[:120]))
        else:
            seen[h] = i + 1
    return [Finding("duplicate_pages", "Duplicated page", "issue", "medium",
                    f"Page {b} has the same text as page {a}.", [ev(b, x, "text")], 0.95,
                    suggested_action="Ask the authors to upload a corrected file.") for a, b, x in dups[:5]]


@check("rotated_pages", "Rotated or landscape pages", "integrity", 1,
       "Pages that are rotated or in landscape orientation.")
def rotated_pages(doc, ctx):
    odd = [p for p in doc["pages"] if p["rotation"] % 360 != 0 or p["width"] > p["height"] * 1.05]
    if not odd:
        return []
    return [Finding("rotated_pages", "Rotated or landscape page(s)", "possible", "low",
                    "Usually a large table or figure page; sometimes a scanning or export problem.",
                    [ev(p["n"], f"rotation {p['rotation']}°, {p['width']:.0f}×{p['height']:.0f} pt", "layout") for p in odd[:10]], 0.7)]


@check("needs_ocr", "Pages without a text layer", "integrity", 1,
       "Pages that look scanned: mostly image, almost no extractable text. Reviewers cannot search them and checks cannot read them.",
       params={"min_chars": 80, "min_image_area": 0.4},
       param_help={"min_chars": "Pages with fewer characters than this...", "min_image_area": "...and at least this share covered by images"})
def needs_ocr(doc, ctx):
    p_ = ctx.params
    pages = [p for p in doc["pages"] if p["n_chars"] < p_["min_chars"] and p["image_area"] >= p_["min_image_area"]]
    if not pages:
        return []
    allp = len(pages) == len(doc["pages"])
    return [Finding("needs_ocr", "Scanned pages (no text layer)" if allp else "Page(s) without a text layer",
                    "issue", "high" if allp else "medium",
                    "The whole paper is an image; none of the text checks could run." if allp
                    else "These pages are images of text; content on them was not checked.",
                    [ev(p["n"], f"{p['n_chars']} characters, {int(p['image_area'] * 100)}% image", "layout") for p in pages[:10]], 0.85,
                    limitations="No OCR is performed.",
                    suggested_action="Ask for a PDF exported directly from the source (LaTeX/Word).")]


@check("broken_glyphs", "Broken symbols", "integrity", 1,
       "Characters without a Unicode mapping, shown as (cid:NN) or �. Symbols, equations or whole words may be unreadable.",
       params={"min_count": 5}, param_help={"min_count": "Report when a page has at least this many"})
def broken_glyphs(doc, ctx):
    lim = int(ctx.params["min_count"])
    out = []
    pages = [p for p in doc["pages"] if p["cid"] + p["fffd"] >= lim]
    if pages:
        evs = []
        for p in pages[:6]:
            t = doc["page_texts"][p["n"] - 1]
            m = re.search(r'\(cid:\d+\)|�', t)
            evs.append(ev(p["n"], docmodel.snippet(t, m.start(), m.end(), 50) if m else f"{p['cid'] + p['fffd']} unmapped characters"))
        total = sum(p["cid"] + p["fffd"] for p in pages)
        out.append(Finding("broken_glyphs", "Unmapped characters (broken symbols)", "possible", "low",
                           f"{total} characters on {len(pages)} page(s) have no Unicode mapping. They may still print correctly, "
                           "but text extraction, search and screen readers see garbage.",
                           evs, 0.7, limitations="Often harmless (math fonts); look at the page before acting."))
    unemb = (doc.get("fonts") or {}).get("unembedded") or []
    if unemb:
        out.append(Finding("broken_glyphs", "Fonts not embedded", "issue", "medium",
                           "Some fonts are not embedded; the paper may render differently on other machines and fail IEEE PDF eXpress.",
                           [ev(None, x, "pdf-fonts") for x in unemb[:5]], 0.9,
                           suggested_action="Ask for a PDF with all fonts embedded."))
    return out


@check("annotations", "Comments and markup left in the PDF", "integrity", 1,
       "Sticky notes, highlights, strike-outs and other annotations (links are ignored).")
def annotations(doc, ctx):
    evs = []
    for p in doc["pages"]:
        for a in p["annots"]:
            evs.append(ev(p["n"], f"{a['subtype']}: {a['contents']}" if a["contents"] else a["subtype"], "annotation"))
    if not evs:
        return []
    return [Finding("annotations", "Annotations left in the PDF", "issue", "low",
                    f"{len(evs)} annotation(s) such as comments or highlights are still in the file. They can reveal "
                    "review history or author identity.", evs[:15], 0.9,
                    suggested_action="Read them; ask for a clean file if they contain anything sensitive.")]


_PLACEHOLDER_RE = re.compile(
    r'\b(?:TODO|TBD|FIXME|XXX+)\b|lorem ipsum|\[citation needed\]|citation needed|'
    r'Error! Reference source not found|\[\?+\]|(?:Fig\.|Figure|Table|Section|Eq\.|Sec\.)\s*\?\?|(?<!\?)\?\?(?!\?)',
    re.I)


@check("placeholders", "Placeholders and unresolved references", "integrity", 1,
       "Leftover TODO/TBD/XXX, lorem ipsum, '??' from unresolved LaTeX references, Word cross-reference errors.")
def placeholders(doc, ctx):
    keep, seen = [], set()
    for i, t in enumerate(doc["page_texts"]):
        # The IEEE template's copyright placeholder ("XXX-X-XXXX-XXXX-X/XX/$XX.00 ©20XX IEEE") is
        # expected in submissions; it is replaced at camera-ready time.
        t = re.sub(r'X{3}-X-X{4}-X{4}-X/XX/\$XX\.00\s*(?:©|\(c\))?\s*20XX\s*IEEE', ' ', t)
        for m in _PLACEHOLDER_RE.finditer(t):
            s = m.group(0)
            # TODO/XXX must be upper case to count (avoid "xxx" in prose / identifiers)
            if re.fullmatch(r'(?i)todo|tbd|fixme|x{3,}', s) and not s.isupper():
                continue
            line_key = (i, t.rfind("\n", 0, m.start()))
            if line_key in seen:
                continue
            seen.add(line_key)
            keep.append(ev(i + 1, docmodel.snippet(t, m.start(), m.end())))
    if not keep:
        return []
    return [Finding("placeholders", "Placeholders or unresolved references", "issue", "medium",
                    f"{len(keep)} leftover placeholder(s) or broken cross-reference(s).", keep[:10], 0.8,
                    suggested_action="Usually a sign of an unfinished draft; note it for the reviewers or ask for a fix.")]


def _norm(s):
    return " ".join(re.sub(r'[^a-z0-9 ]+', ' ', (s or "").lower()).split())


@check("metadata_match", "PDF matches the submitted title and abstract", "integrity", 1,
       "Compares the title and abstract in the PDF with those entered in the submission system. "
       "A mismatch can mean the wrong file was uploaded.",
       params={"min_title_similarity": 80, "min_abstract_similarity": 60})
def metadata_match(doc, ctx):
    out = []
    st = ctx.paper.get("title") or ""
    if st and doc.get("title_guess"):
        ft = doc["title_guess"]
        sim = max(fuzz.token_set_ratio(_norm(st), _norm(ft)),
                  fuzz.partial_ratio(_norm(st), _norm(" ".join(doc["page_texts"][:1])[:1500])))
        if sim < ctx.params["min_title_similarity"]:
            out.append(Finding("metadata_match", "PDF title differs from the submitted title", "possible", "medium",
                               f"Similarity {sim:.0f}%. Submitted: “{st[:150]}”.",
                               [ev(1, ft, "text")], 0.7,
                               limitations="The PDF title is guessed from the largest text on page 1.",
                               suggested_action="Check that the right file was uploaded; small wording changes are common."))
    sa = ctx.paper.get("abstract") or ""
    if len(sa.split()) >= 30 and doc.get("abstract"):
        sim = fuzz.token_set_ratio(_norm(sa), _norm(doc["abstract"]))
        if sim < ctx.params["min_abstract_similarity"]:
            out.append(Finding("metadata_match", "PDF abstract differs from the submitted abstract", "possible", "low",
                               f"Similarity {sim:.0f}%. The abstract in the submission system may be outdated or belong to another paper.",
                               [ev(1, doc["abstract"][:250], "text")], 0.6))
    return out


@check("same_file_elsewhere", "Same file submitted as another paper", "integrity", 5,
       "The identical PDF (same hash) is also attached to another submission in this conference.", volatile=True)
def same_file_elsewhere(doc, ctx):
    others = ctx.store.papers_with_hash(doc["sha256"], ctx.paper.get("paper_id"))
    if not others:
        return []
    return [Finding("same_file_elsewhere", "Identical file in another submission", "issue", "high",
                    f"The same PDF is attached to submission(s) {', '.join(others[:10])}.",
                    [ev(None, f"sha256 {doc['sha256'][:16]}... also in {', '.join(others[:10])}", "file-hash")], 1.0,
                    suggested_action="Check for a duplicate submission or an upload mistake.")]
