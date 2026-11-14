"""Section 8 -- manipulation (deterministic part).

Evidence only. There is deliberately no "probability this was AI-written"
score: such detectors are unreliable and unfair to non-native writers.
"""

import re

from .registry import check
from .findings import Finding, ev
from . import docmodel

_TEMPLATE_TEXT = re.compile(
    r'(?i)template|given\s*name\s*surname|name of organization|dept\.?\s*name|city,?\s*country|'
    r'email address or orcid|conference papers?|prior to submission|line\s*\d\s*:')

_REASON = {"white": "white text on a white background", "tiny": "text smaller than 3 pt", "offpage": "text placed outside the page"}


@check("hidden_text", "Hidden text", "manipulation", 8,
       "Text a reader cannot see but software (and AI reviewing tools) can read: white-on-white, microscopic, or placed off the page.", version=2)
def hidden_text(doc, ctx):
    out = []
    for reason in ("white", "tiny", "offpage"):
        items = [(p["n"], h) for p in doc["pages"] for h in p["hidden"] if h["reason"] == reason]
        # ignore single symbols / numbers (white axis ticks, figure artefacts)
        items = [(n, h) for n, h in items if len(re.findall(r'[A-Za-z]{2,}', h["text"])) >= 2]
        if not items:
            continue
        if reason == "white":
            tmpl_pages = {n for n, h in items if _TEMPLATE_TEXT.search(h["text"])}
            tmpl = [(n, h) for n, h in items if n in tmpl_pages]  # whole hidden template paragraph
            if tmpl:
                out.append(Finding("hidden_text", "Template text hidden in white", "possible", "low",
                                   "Instructions or placeholders from the conference template were coloured white instead of deleted. "
                                   "Harmless in itself, but sloppy, and it hides content from readers.",
                                   [ev(n, h["text"], "layout (white text)") for n, h in tmpl[:4]], 0.8,
                                   suggested_action="No action needed unless other white text is present."))
                items = [x for x in items if x not in tmpl]
                if not items:
                    continue
        words = sum(len(h["text"].split()) for _, h in items)
        # Tiny and off-page text is common inside scaled-down figures; only a run of
        # white prose is strong evidence. Hidden instructions are reported by prompt_injection.
        strong = reason == "white" and words >= 15
        out.append(Finding("hidden_text", f"Hidden text: {_REASON[reason]}", "issue" if strong else "possible",
                           "medium" if strong else "low",
                           f"{len(items)} piece(s), about {words} words, of {_REASON[reason]}.",
                           [ev(n, h["text"], f"layout ({_REASON[reason]})") for n, h in items[:8]],
                           0.8 if strong else 0.45,
                           limitations="White text inside figures drawn on a dark background, or tiny text in plots, can be harmless. "
                                       "Text hidden with invisible rendering mode is not detected.",
                           suggested_action="Read the hidden text; instructions aimed at reviewers or AI tools are a serious concern."))
    return out


@check("invisible_chars", "Invisible Unicode characters", "manipulation", 8,
       "Zero-width and Unicode 'tag' characters, which can smuggle text past a human reader.",
       params={"min_zero_width": 20})
def invisible_chars(doc, ctx):
    out = []
    tags = [(p["n"], p["tag_chars"]) for p in doc["pages"] if p["tag_chars"]]
    if tags:
        out.append(Finding("invisible_chars", "Unicode tag characters", "issue", "high",
                           "Tag characters (U+E0000 block) render as nothing but carry hidden ASCII text.",
                           [ev(n, f"{c} tag characters", "text") for n, c in tags[:6]], 0.9))
    zw = [(p["n"], p["zero_width"]) for p in doc["pages"] if p["zero_width"] >= ctx.params["min_zero_width"]]
    if zw:
        out.append(Finding("invisible_chars", "Many zero-width characters", "possible", "low",
                           "Many zero-width characters; usually harmless (soft hyphens from Word) but can hide or split words to evade checks.",
                           [ev(n, f"{c} zero-width characters", "text") for n, c in zw[:6]], 0.4))
    return out


_INJECTION = re.compile(
    r'(?i)\bignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|directions?)|'
    r'\b(?:disregard|forget)\s+(?:all\s+)?(?:previous|prior|your)\s+(?:instructions?|guidelines?)|'
    r'\b(?:give|write|provide|generate)\s+(?:a|an|only)?\s*(?:very\s+|highly\s+)?(?:positive|favou?rable|glowing)\s+(?:review|evaluation|assessment|feedback)|'
    r'\b(?:recommend|suggest)\s+(?:this\s+paper\s+)?(?:for\s+)?(?:strong\s+)?accept(?:ance)?\b|'
    r'\bdo\s+not\s+(?:highlight|mention|point\s+out|list)\s+(?:any\s+)?(?:negatives?|weakness(?:es)?|flaws?|limitations?)|'
    r'\b(?:if\s+you\s+are|as)\s+an?\s+(?:ai|llm|language\s+model|large\s+language\s+model|automated\s+reviewer|ai\s+reviewer)\b|'
    r'\b(?:llm|ai|chatgpt|gpt|claude|gemini)\s+reviewers?\b|'
    r'\bnote\s+to\s+(?:the\s+)?(?:ai|llm|reviewers?|language\s+model)\b|'
    r'\byou\s+are\s+(?:now\s+)?an?\s+(?:helpful\s+)?(?:assistant|ai|reviewer|language\s+model)\b|'
    r'\bsystem\s+prompt\b')


# Same idea on text whose spaces were lost (hidden text is often set without proper spacing)
_COMPACT_INJECTION = re.compile(
    r'ignore(?:all|any)?(?:the)?(?:previous|prior|above)instructions|disregard(?:all)?(?:previous|prior|your)instructions|'
    r'(?:give|write)(?:a|an)?(?:very|highly)?positivereview|recommendaccept|donothighlight(?:any)?(?:negatives|weaknesses)|'
    r'llmreviewer|aireviewer|asalanguagemodel|youareanai')


@check("prompt_injection", "Instructions aimed at reviewers or AI tools", "manipulation", 8,
       "Prompt-like text such as 'ignore previous instructions' or 'give a positive review', visible or hidden.")
def prompt_injection(doc, ctx):
    out = []
    hidden_txt = [(p["n"], h["text"]) for p in doc["pages"] for h in p["hidden"]]
    for n, t in hidden_txt:
        m = _INJECTION.search(t) or _COMPACT_INJECTION.search(re.sub(r'[^a-z]', '', t.lower()))
        if m:
            out.append(Finding("prompt_injection", "Hidden instruction to reviewers/AI", "issue", "high",
                               "Hidden text contains an instruction addressed to reviewers or AI tools.",
                               [ev(n, t, "hidden text")], 0.95,
                               suggested_action="Serious: report to the chairs/steering committee per the conference policy."))
    seen = set()
    for page, ex, m in docmodel.iter_matches(doc, _INJECTION, limit=10):
        if (page, m.group(0).lower()) in seen:
            continue
        seen.add((page, m.group(0).lower()))
        # a paper ABOUT prompt injection / LLMs will mention these phrases legitimately
        out.append(Finding("prompt_injection", "Prompt-like phrase in the text", "possible", "medium",
                           "Visible text contains a phrase typical of instructions to AI systems. "
                           "Papers about LLMs or security may use it legitimately.",
                           [ev(page, ex)], 0.4,
                           suggested_action="Read the context; it matters only if it addresses the reviewer or a reviewing tool."))
    return out


_AI_LEFTOVER = re.compile(
    r'(?i)\bas\s+an\s+ai\s+(?:language\s+)?model\b|\bas\s+a\s+large\s+language\s+model\b|'
    r'\bcertainly[!,]\s+here\s+(?:is|are)\b|\bsure[!,]\s+here\s+(?:is|are)\b|\bhere\s+is\s+(?:a|the)\s+(?:revised|rewritten|improved|polished)\s+version\b|'
    r'\bi\s+hope\s+this\s+helps\b|\bregenerate\s+response\b|\bas\s+of\s+my\s+(?:last\s+)?knowledge\s+(?:update|cutoff)\b|'
    r'\bi\s+(?:cannot|can\'t)\s+(?:fulfil+|assist\s+with)\s+(?:this|that)\s+request\b|'
    r'\[insert\s+[^\]]{2,40}\]|\bin\s+this\s+revised\s+version,\s+i\b')


@check("ai_leftovers", "Leftover chatbot phrases", "manipulation", 8,
       "Phrases pasted from a chatbot answer, e.g. 'As an AI language model', 'Certainly! Here is', '[insert citation]'.")
def ai_leftovers(doc, ctx):
    hits = list(docmodel.iter_matches(doc, _AI_LEFTOVER, limit=8))
    if not hits:
        return []
    return [Finding("ai_leftovers", "Chatbot text left in the paper", "possible", "medium",
                    f"{len(hits)} phrase(s) typical of copied chatbot output.",
                    [ev(p, ex) for p, ex, _ in hits], 0.7,
                    limitations="Evidence of careless editing, not proof of undisclosed AI use; check the call's AI-disclosure policy.",
                    suggested_action="Compare with the paper's AI-use disclosure, if the call requires one.")]
