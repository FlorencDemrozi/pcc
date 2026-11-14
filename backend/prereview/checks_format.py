"""Section 2 -- formatting (page geometry, fonts, spacing, structure)."""

import re
import statistics

from .registry import check
from .findings import Finding, ev

_SIZES = {"letter": (612, 792), "a4": (595.3, 841.9)}


@check("page_limit", "Page limit", "formatting", 2,
       "Body pages (before the references) and total pages against the limit set on the Conference tab.",
       params={"extra_ref_pages": 0},
       param_help={"extra_ref_pages": "Extra pages allowed for references when they count towards the limit (0 = none)"})
def page_limit(doc, ctx):
    mx = int(ctx.conf.get("max_pages") or 0)
    if mx <= 0:
        return []
    n = doc["n_pages"]
    ref = doc.get("ref_page")
    body = (ref if ref else n)  # the references page itself usually still has body text
    if ctx.conf.get("refs_excluded"):
        if ref and ref - 1 > mx:
            return [Finding("page_limit", "Over the page limit", "issue", "high",
                            f"References start on page {ref}, so the body is more than {mx} pages.",
                            [ev(ref, f"{n} pages in total; references heading on page {ref}", "layout")], 0.9,
                            suggested_action="Desk-reject or ask for a shortened version, per the call.")]
        if not ref and n > mx:
            return [Finding("page_limit", "Possibly over the page limit", "possible", "medium",
                            f"{n} pages and no references heading found, so the body length could not be separated.",
                            [ev(None, f"{n} pages", "layout")], 0.5)]
        return []
    allowed = mx + int(ctx.params.get("extra_ref_pages") or 0)
    if n > allowed:
        sev = "high" if body > mx else "medium"
        return [Finding("page_limit", "Over the page limit", "issue", sev,
                        f"{n} pages; the limit is {mx}" + (f" (+{allowed - mx} for references)" if allowed > mx else "") + ".",
                        [ev(None, f"{n} pages" + (f"; references start on page {ref}" if ref else ""), "layout")], 0.95,
                        suggested_action="Desk-reject or ask for a shortened version, per the call.")]
    return []


@check("paper_size", "Paper size", "formatting", 2,
       "All pages use the paper size required by the call (Letter or A4).",
       params={"tolerance_pt": 6})
def paper_size(doc, ctx):
    want = (ctx.conf.get("paper_size") or "any").lower()
    tol = float(ctx.params["tolerance_pt"])
    sizes = {}
    for p in doc["pages"]:
        w, h = sorted((p["width"], p["height"]))
        sizes.setdefault((round(w), round(h)), []).append(p["n"])
    out = []
    if len(sizes) > 1:
        out.append(Finding("paper_size", "Mixed page sizes", "possible", "low",
                           "Pages use different sizes: " + "; ".join(f"{w}×{h} pt on pages {', '.join(map(str, ps[:6]))}"
                                                                       for (w, h), ps in sizes.items()) + ".",
                           [ev(ps[0], f"{w}×{h} pt", "layout") for (w, h), ps in list(sizes.items())[:4]], 0.8))
    if want in _SIZES:
        tw, th = _SIZES[want]
        wrong = [(k, ps) for k, ps in sizes.items() if abs(k[0] - tw) > tol or abs(k[1] - th) > tol]
        if wrong:
            out.append(Finding("paper_size", f"Not {want.upper() if want == 'a4' else 'US Letter'} size", "issue", "medium",
                               f"Expected {tw:.0f}×{th:.0f} pt.",
                               [ev(ps[0], f"{w}×{h} pt on {len(ps)} page(s)", "layout") for (w, h), ps in wrong[:4]], 0.9,
                               suggested_action="Usually means the wrong template or a print-to-PDF; ask for the correct size."))
    return out


@check("margins", "Margins and printable area", "formatting", 2,
       "Text that runs into the page margins or off the page.",
       params={"min_margin_pt": 28, "skip_first_page_top": True},
       param_help={"min_margin_pt": "Text closer to the page edge than this is reported (28 pt ≈ 1 cm)",
                   "skip_first_page_top": "Ignore the top of page 1 (conference headers / copyright lines)"})
def margins(doc, ctx):
    m = float(ctx.params["min_margin_pt"])
    evs = []
    pages = set()
    for p in doc["pages"]:
        w, h = p["width"], p["height"]
        for ln in p["lines"]:
            if len(ln["t"]) < 4 or re.fullmatch(r'[\d\s\-–—/of]+', ln["t"]):
                continue  # page numbers
            if p["n"] == 1 and ctx.params.get("skip_first_page_top") and ln["top"] < h * 0.1:
                continue
            side = None
            if ln["x0"] < m: side = f"left ({ln['x0']:.0f} pt from edge)"
            elif ln["x1"] > w - m: side = f"right ({w - ln['x1']:.0f} pt from edge)"
            elif ln["top"] < m * 0.6: side = f"top ({ln['top']:.0f} pt from edge)"
            elif ln["bottom"] > h - m * 0.6: side = f"bottom ({h - ln['bottom']:.0f} pt from edge)"
            if side:
                pages.add(p["n"])
                if len(evs) < 10:
                    evs.append(ev(p["n"], f"[{side}] {ln['t'][:120]}", "layout"))
    if not evs:
        return []
    return [Finding("margins", "Text in the margins", "issue" if len(pages) >= 2 else "possible", "medium",
                    f"Text on {len(pages)} page(s) runs into the margin. Often a sign of squeezed layout to fit the page limit.",
                    evs, 0.7, limitations="Headers, footers and line numbers added by some templates can trigger this.",
                    suggested_action="Look at the listed pages; compare with the template.")]


@check("font_size", "Body font size", "formatting", 2,
       "The running-text font size is not smaller than allowed.",
       params={"min_body_pt": 9.5}, param_help={"min_body_pt": "Smallest acceptable body font size (IEEE: 10 pt)"})
def font_size(doc, ctx):
    bs = doc.get("body_size") or 0
    if not bs:
        return []
    if bs < float(ctx.params["min_body_pt"]) - 0.05:
        return [Finding("font_size", "Body font smaller than allowed", "issue", "medium",
                        f"Most of the text is set in {bs:.1f} pt (minimum {ctx.params['min_body_pt']} pt).",
                        [ev(None, f"dominant size {bs:.1f} pt", "layout")], 0.85,
                        suggested_action="Shrinking the font is a common way to beat the page limit.")]
    # pages where the body text is clearly smaller than in the rest of the paper
    # pages before the references (reference lists are legitimately set smaller)
    evs = []
    last_body = (doc.get("ref_page") or doc["n_pages"] + 1) - 1
    for p in doc["pages"][:last_body]:
        sz = [ln["size"] for ln in p["lines"] if len(ln["t"]) > 40]
        if len(sz) >= 25:
            med = statistics.median(sz)
            if med < bs - 0.7:
                evs.append(ev(p["n"], f"body text {med:.1f} pt vs {bs:.1f} pt elsewhere", "layout"))
    if evs:
        return [Finding("font_size", "Smaller text on some pages", "possible", "low",
                        "The running text is smaller on these pages than in the rest of the paper.", evs[:8], 0.6,
                        limitations="Pages that are mostly tables or captions can trigger this.")]
    return []


@check("line_spacing", "Squeezed line spacing", "formatting", 2,
       "Line spacing that is tighter than normal for the font size, or tighter on some pages than on others.",
       params={"min_ratio": 1.05, "page_drop": 0.92},
       param_help={"min_ratio": "Minimum baseline distance / font size", "page_drop": "Report pages below this share of the paper's usual spacing"})
def line_spacing(doc, ctx):
    bs = doc.get("body_size") or 0
    if not bs:
        return []
    per_page = {}
    for p in doc["pages"]:
        lines = [ln for ln in p["lines"] if abs(ln["size"] - bs) < 0.3 and len(ln["t"]) > 30]
        lines.sort(key=lambda l: (round(l["x0"] / 150), l["top"]))
        gaps = []
        for a, b in zip(lines, lines[1:]):
            g = b["top"] - a["top"]
            if 0.8 * bs < g < 2.0 * bs and abs(a["x0"] - b["x0"]) < 40:
                gaps.append(g)
        if len(gaps) >= 10:
            per_page[p["n"]] = statistics.median(gaps)
    if not per_page:
        return []
    doc_med = statistics.median(per_page.values())
    out = []
    ratio = doc_med / bs
    if ratio < float(ctx.params["min_ratio"]):
        out.append(Finding("line_spacing", "Line spacing tighter than normal", "possible", "medium",
                           f"Baselines are {doc_med:.1f} pt apart for {bs:.1f} pt text (ratio {ratio:.2f}; templates use about 1.15–1.2).",
                           [ev(None, f"median line pitch {doc_med:.1f} pt", "layout")], 0.6))
    drop = float(ctx.params["page_drop"])
    tight = [(n, g) for n, g in per_page.items() if g < doc_med * drop]
    if tight:
        out.append(Finding("line_spacing", "Tighter spacing on some pages", "possible", "low",
                           "These pages have noticeably smaller line spacing than the rest of the paper (e.g. \\vspace or \\linespread tricks).",
                           [ev(n, f"line pitch {g:.1f} pt vs {doc_med:.1f} pt", "layout") for n, g in tight[:8]], 0.55))
    return out


@check("abstract_keywords", "Abstract length and keywords", "formatting", 2,
       "The abstract in the PDF has a reasonable length and keywords / index terms are present.",
       params={"min_words": 70, "max_words": 300, "require_keywords": True})
def abstract_keywords(doc, ctx):
    out = []
    a = doc.get("abstract") or ""
    n = len(a.split())
    if not a:
        out.append(Finding("abstract_keywords", "No abstract found in the PDF", "possible", "low",
                           "No 'Abstract' heading was found on the first pages.", [ev(1, (doc["page_texts"] or [""])[0][:150])], 0.5))
    elif n < ctx.params["min_words"] or n > ctx.params["max_words"]:
        out.append(Finding("abstract_keywords", "Abstract length out of range", "possible", "low",
                           f"{n} words (expected {ctx.params['min_words']}–{ctx.params['max_words']}).",
                           [ev(1, a[:200])], 0.6, limitations="The abstract end is detected heuristically."))
    if ctx.params.get("require_keywords") and not doc.get("keywords_text"):
        out.append(Finding("abstract_keywords", "No keywords / index terms", "possible", "low",
                           "The template asks for keywords (IEEE: 'Index Terms').", [ev(1, "")], 0.6))
    return out


_REQ_DEFAULT = ["Introduction", "Conclusion", "References"]
_SYNONYMS = {
    "introduction": r"introduction|motivation",
    "conclusion": r"conclusions?|concluding remarks|summary|conclusion and future work|conclusions and future work|discussion and conclusions?",
    "references": r"references|bibliography",
    "related work": r"related works?|background|state of the art|prior work|literature review",
    "evaluation": r"evaluation|experiments?|experimental results|results|experimental setup",
}


@check("required_sections", "Required sections", "formatting", 2,
       "The paper has the sections the call requires for its paper type.",
       params={"sections": _REQ_DEFAULT},
       param_help={"sections": "Section names that must appear (synonyms like 'Conclusions' or 'Summary' are accepted)"})
def required_sections(doc, ctx):
    from rapidfuzz import fuzz
    have = " | ".join(s["title"].lower() for s in doc.get("sections", []))
    compact = [re.sub(r'[^a-z]', '', s["title"].lower()) for s in doc.get("sections", [])]
    text = doc.get("full_text", "").lower()
    missing = []
    for s in ctx.params.get("sections") or []:
        pat = _SYNONYMS.get(s.lower(), re.escape(s.lower()))
        if re.search(r'\b(' + pat + r')\b', have):
            continue
        # headings with lost spaces / a dropped first letter ("CONCLUSIONANDDISCUSSION", "ONCLUSION")
        alts = [re.sub(r'[^a-z|]', '', a) for a in pat.replace('?', '').split('|')]
        if any(a and (a in c or (len(c) >= 5 and fuzz.partial_ratio(a, c) >= 85)) for a in alts for c in compact):
            continue
        # fall back to a heading-looking line in the text
        if re.search(r'(?m)^\s*(?:[ivx]+\.|\d+\.?)?\s*(' + pat + r')\s*$', text):
            continue
        missing.append(s)
    if not missing:
        return []
    return [Finding("required_sections", "Missing section(s)", "possible", "low",
                    "Not found: " + ", ".join(missing) + ".",
                    [ev(None, "Detected headings: " + (", ".join(s["title"] for s in doc.get("sections", [])[:15]) or "none"), "layout")],
                    0.55, limitations="Heading detection is heuristic; unusual headings may be missed.")]


_TEMPLATES = {
    "ieee": [r"\bindex terms\b", r"nimbusromno9l|times", r"^\s*I\.\s+INTRODUCTION"],
    "acm": [r"ccs concepts", r"acm reference format", r"libertine|linlibertine"],
    "lncs": [r"\bkeywords:", r"cmr10|cmr9|sfrm|lmroman", r"^\s*1\s+Introduction"],
}


def _template_scores(doc):
    text = doc.get("full_text", "")[:20000]
    fonts = " ".join({ln["font"].lower() for p in doc["pages"][:2] for ln in p["lines"]})
    scores = {}
    for name, pats in _TEMPLATES.items():
        s = 0
        for pat in pats:
            if re.search(pat, text, re.I | re.M) or re.search(pat, fonts, re.I):
                s += 1
        scores[name] = s
    # two-column letter/A4 with ~10pt body -> IEEE; single column ~345pt text width -> LNCS
    return scores


@check("template", "Template", "formatting", 2,
       "Fingerprint of the template used (IEEE, ACM, LNCS) compared with the one the call requires.")
def template(doc, ctx):
    want = (ctx.conf.get("template") or "any").lower()
    if want not in _TEMPLATES:
        return []
    scores = _template_scores(doc)
    best = max(scores, key=scores.get)
    if scores[want] >= 2 or scores[best] < 2 or best == want:
        return []
    return [Finding("template", "Different template", "possible", "medium",
                    f"The paper looks like the {best.upper()} template, not {want.upper()}.",
                    [ev(None, ", ".join(f"{k.upper()} {v}/3" for k, v in scores.items()), "layout")], 0.6,
                    limitations="Fingerprint uses fonts and typical phrases; customised templates can confuse it.")]
