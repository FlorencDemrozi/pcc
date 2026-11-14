"""Section 11 -- numbers (deterministic part). Scientific concerns, kept
separate from technical compliance; each is a prompt for a closer look."""

import re

from .registry import check
from .findings import Finding, ev
from . import docmodel

_BOUNDED = r'(?:accuracy|precision|recall|f1(?:[- ]score)?|f-score|f-measure|auc|sensitivity|specificity|' \
           r'utili[sz]ation|yield|coverage|fault coverage|hit rate|miss rate|success rate|top-?[15] accuracy)'
_PCT_OVER = re.compile(r'(?i)\b' + _BOUNDED + r'\s*(?:of|=|:|is|was|reaches|reached|achieves?|achieved|up to|about|around)?\s*'
                       r'(?P<v>\d{3,}(?:\.\d+)?|1\d\d(?:\.\d+)?)\s*%')
_UNIT_OVER = re.compile(r'(?i)\b(?:f1(?:[- ]score)?|auc|roc[- ]auc|precision|recall|r\^?2|r-squared)\s*(?:of|=|:|is|was|score of)?\s*'
                        r'(?P<v>[1-9]\.\d+|-0\.\d+)(?!\s*[%x×])')
_NEG_PCT = re.compile(r'(?i)\b' + _BOUNDED + r'\s*(?:of|=|:|is|was)?\s*(?P<v>-\s?\d+(?:\.\d+)?)\s*%')


@check("impossible_values", "Impossible values", "numbers", 11,
       "Metrics outside their possible range: accuracy above 100%, F1/AUC above 1, negative accuracy.",
       kind="scientific")
def impossible_values(doc, ctx):
    evs = []
    body = docmodel.body_text(doc)
    for rx in (_PCT_OVER, _UNIT_OVER, _NEG_PCT):
        for page, ex, m in docmodel.iter_matches(doc, rx, text=body, limit=10):
            try:
                v = float(m.group("v").replace(" ", ""))
            except ValueError:
                continue
            if rx is _PCT_OVER and v <= 100:
                continue
            evs.append(ev(page, ex))
    if not evs:
        return []
    return [Finding("impossible_values", "Value outside its possible range", "possible", "medium",
                    f"{len(evs)} reported metric value(s) cannot be right as written.", evs[:8], 0.6,
                    limitations="Text extraction can merge numbers (e.g. '98.5 1%' from tables); check the PDF.",
                    suggested_action="Typo or a real error; reviewers should be told.")]


_FRACTION = re.compile(r'(?i)\b(?P<a>\d{1,6})\s*(?:out\s+of|of\s+the|of|/)\s*(?P<b>\d{1,6})\b[^.%]{0,40}?\(\s*(?P<p>\d{1,3}(?:\.\d+)?)\s*%\s*\)')


@check("fraction_mismatch", "Counts that disagree with percentages", "numbers", 11,
       "'45 out of 50 (95%)' style statements where the percentage does not match the counts.",
       kind="scientific", params={"tolerance_pp": 1.5})
def fraction_mismatch(doc, ctx):
    evs = []
    for page, ex, m in docmodel.iter_matches(doc, _FRACTION, limit=30):
        a, b, p = int(m.group("a")), int(m.group("b")), float(m.group("p"))
        if b == 0 or a > b:
            continue
        real = 100.0 * a / b
        if abs(real - p) > float(ctx.params["tolerance_pp"]):
            evs.append(ev(page, f"{ex}  → {a}/{b} = {real:.1f}%, reported {p:g}%"))
    if not evs:
        return []
    return [Finding("fraction_mismatch", "Percentage does not match the counts", "possible", "medium",
                    f"{len(evs)} statement(s) where the percentage differs from the counts given.", evs[:8], 0.65)]


_CHANGE = r'(?:improvement|reduction|increase|decrease|speed-?up|gain|saving|savings|drop|decline|rise|lower|higher|faster|smaller|less|more|better)'
_FROM_TO = re.compile(
    r'(?i)\bfrom\s+(?P<x>\d+(?:\.\d+)?)\s*(?P<u1>%|[a-zµμ]{0,4})\s+to\s+(?P<y>\d+(?:\.\d+)?)\s*(?P<u2>%|[a-zµμ]{0,4})'
    r'\s*[,(]?\s*(?:i\.e\.,?\s*|which\s+is\s+|representing\s+|corresponding\s+to\s+|an?\s+|a\s+total\s+)?'
    r'(?:(?P<z>\d+(?:\.\d+)?)\s*(?P<k>%|x|×|times)\s*' + _CHANGE +
    r'|' + _CHANGE + r'\s+(?:of|by)\s+(?:about\s+|around\s+|nearly\s+|over\s+)?(?P<z2>\d+(?:\.\d+)?)\s*(?P<k2>%|x|×|times))')


@check("improvement_recalc", "Reported improvements recalculated", "numbers", 11,
       "'From X to Y, a Z% improvement' statements where Z does not follow from X and Y.",
       kind="scientific", params={"tolerance_rel": 0.1})
def improvement_recalc(doc, ctx):
    evs = []
    tol = float(ctx.params["tolerance_rel"])
    for page, ex, m in docmodel.iter_matches(doc, _FROM_TO, limit=30):
        if m.group("u1") and m.group("u2") and m.group("u1").lower() != m.group("u2").lower():
            continue  # different units (1 µs to 1 s): not comparable here
        x, y = float(m.group("x")), float(m.group("y"))
        z = float(m.group("z") or m.group("z2"))
        if x == 0 or y == 0 or z == 0:
            continue
        k = (m.group("k") or m.group("k2")).lower()
        if k == "%":
            cands = [abs(y - x) / x * 100, abs(y - x) / y * 100]
            if m.group("u1") == "%" and m.group("u2") == "%":
                cands.append(abs(y - x))  # percentage points
        else:
            cands = [max(x, y) / min(x, y)]
        if min(abs(c - z) / max(z, 1e-9) for c in cands) > tol:
            evs.append(ev(page, f"{ex}  → recomputed " + " or ".join(f"{c:.3g}" for c in cands) + f", reported {z:g}{k}"))
    if not evs:
        return []
    return [Finding("improvement_recalc", "Improvement does not follow from the numbers", "possible", "low",
                    f"{len(evs)} statement(s) where the stated improvement differs from the values given by more than {tol:.0%}.",
                    evs[:8], 0.5, limitations="The sentence may compare different quantities; read it before acting.")]
