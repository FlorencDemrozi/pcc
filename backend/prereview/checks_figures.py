"""Section 15 -- figures and tables (deterministic part)."""

import re

from .registry import check
from .findings import Finding, ev
from . import docmodel

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
          "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20}


def _num(label):
    if label.isdigit():
        return int(label)
    return _ROMAN.get(label)


def _captions(doc):
    """First caption per (kind, label), main-text only (appendix labels like A.1 skipped)."""
    seen, out = set(), []
    for c in doc.get("captions", []):
        k = (c["kind"], c["label"])
        if k in seen or _num(c["label"]) is None:
            continue
        seen.add(k); out.append(c)
    return out


@check("caption_numbering", "Figure and table numbering", "figures", 15,
       "Captions numbered in sequence, without gaps or repeats.")
def caption_numbering(doc, ctx):
    out = []
    for kind in ("figure", "table"):
        nums = [_num(c["label"]) for c in _captions(doc) if c["kind"] == kind]
        if len(nums) < 2:
            continue
        gaps = sorted(set(range(1, max(nums) + 1)) - set(nums))
        if gaps and len(gaps) <= 5:
            out.append(Finding("caption_numbering", f"{kind.capitalize()} numbering has gaps", "possible", "low",
                               f"No caption found for {kind} " + ", ".join(map(str, gaps)) + ".",
                               [ev(None, f"{kind}s found: " + ", ".join(map(str, sorted(nums))), "layout")], 0.5,
                               limitations="Captions split across lines or placed inside images can be missed."))
    return out


@check("uncited_figures", "Figures and tables never referred to", "figures", 15,
       "Each figure and table should be mentioned in the text.", version=2)
def uncited_figures(doc, ctx):
    body = docmodel.body_text(doc)
    flat = " ".join(body.split())
    flat = re.sub(r'([A-Za-z])- ([a-z])', r'\1\2', flat)  # "Fig- ure 1" (hyphenated line break)
    missing = []
    for c in _captions(doc):
        lab = re.escape(c["label"])
        if c["kind"] == "figure":
            pat = r'(?i)\b(?:fig(?:ure)?s?\.?)[\s\-\u2013~]*(?:\d+[a-z]?\s*(?:,|and|&|-|–)\s*)*' + lab + r'(?![0-9IVX])'
        else:
            pat = r'(?i)\b(?:tables?|tab\.)[\s\-\u2013~]*(?:[0-9IVX]+\s*(?:,|and|&|-|–)\s*)*' + lab + r'(?![0-9IVX])'
        mentions = len(re.findall(pat, flat))
        if mentions <= 1:  # the caption itself is one match
            missing.append(c)
    if not missing:
        return []
    return [Finding("uncited_figures", "Figure/table not referred to in the text", "possible", "low",
                    ", ".join(f"{c['kind'].capitalize()} {c['label']}" for c in missing[:10]) + " is never mentioned in the text.",
                    [ev(c["page"], c["text"], "caption") for c in missing[:8]], 0.5,
                    limitations="Ranges like 'Figs. 2–4' are partly handled; references to sub-figures can be missed.")]
