"""
affiliation_expander.py — automatic synonym expansion for institution affiliations.

Two-stage pipeline:
  1. ROR (Research Organization Registry) v2 API — free, no key, 100k+ institutions
  2. LLM fallback — for abbreviations, misspellings, informal names ROR misses

Call expand_affiliations(affiliation_strings) once before the COI check.
Returns a dict: { canonical_name: [variant1, variant2, ...] }
"""

import asyncio
import re
from typing import Optional
import httpx


# ── ROR API ───────────────────────────────────────────────────────────────────
# ROR API/schema v1 was sunset in December 2025 (v1 requests return 410), so
# the v2 endpoint and v2 record shape (organization.names[]) are used.

ROR_API = "https://api.ror.org/v2/organizations"
ROR_TIMEOUT = 8.0          # seconds per request
ROR_CONCURRENCY = 5        # max parallel requests
ROR_OVERALL_CAP = 30.0     # seconds for the whole ROR stage (partial results kept)


def _clean_affiliation(aff: str) -> str:
    """Reduce an affiliation to its institution-level segment for lookup
    (drops department/lab prefixes and trailing city/country segments)."""
    try:
        from coi_checker import _institution_parts, _norm_aff
        segs = [s.strip() for s in re.split(r'[,;\n|]+', aff or "") if s.strip()]
        inst_norm, qual_norm = _institution_parts(aff)
        # Return the original-cased institution segment (+ campus qualifier,
        # e.g. "University of California, Davis")
        for i, s in enumerate(segs):
            if _norm_aff(s) == inst_norm:
                if qual_norm and i + 1 < len(segs) and _norm_aff(segs[i + 1]) == qual_norm:
                    return f"{s}, {segs[i + 1]}"
                return s
        if inst_norm:
            return inst_norm
    except Exception:
        pass
    parts = [p.strip() for p in (aff or "").split(',') if p.strip()]
    return max(parts, key=len) if parts else (aff or "").strip()


def _parse_ror_v2_item(item: dict) -> Optional[dict]:
    org = item.get("organization") or {}
    names = org.get("names") or []
    canonical = ""
    aliases, acronyms, labels = [], [], []
    for n in names:
        if not isinstance(n, dict):
            continue
        val = (n.get("value") or "").strip()
        if not val:
            continue
        types = n.get("types") or []
        if "ror_display" in types and not canonical:
            canonical = val
        if "acronym" in types:
            acronyms.append(val)
        elif "alias" in types:
            aliases.append(val)
        elif "label" in types:
            labels.append(val)
    if not canonical:
        canonical = (labels[0] if labels else (org.get("name") or "")).strip()
    if not canonical:
        return None
    return {
        "canonical": canonical,
        "aliases":   aliases,
        "acronyms":  acronyms,
        "labels":    labels,
        "score":     item.get("score", 0),
        "id":        org.get("id", ""),
    }


async def _ror_lookup(client: httpx.AsyncClient, affiliation: str) -> Optional[dict]:
    """
    Query ROR (v2 affiliation matching) for a single affiliation string.
    Returns the match ROR marks as `chosen` (ROR's recommended signal for
    automatic selection), or None. Never raises.
    """
    query = _clean_affiliation(affiliation)
    if len(query) < 4:
        return None
    try:
        r = await client.get(ROR_API, params={"affiliation": query}, timeout=ROR_TIMEOUT)
        if r.status_code != 200:
            return None
        items = (r.json() or {}).get("items", []) or []
        for it in items:
            if it.get("chosen"):
                return _parse_ror_v2_item(it)
    except Exception:
        pass
    return None


async def _ror_expand_batch(affiliations: list[str],
                            overall_cap: float = ROR_OVERALL_CAP,
                            per_request_timeout: float = ROR_TIMEOUT) -> dict[str, list[str]]:
    """
    Query ROR for all unique affiliations concurrently, with one shared
    client, a semaphore, a per-request timeout and an overall cap. Results
    of requests that finished before the cap are kept; the rest are cancelled.
    Returns { canonical → [variants] }
    """
    result: dict[str, list[str]] = {}
    sem = asyncio.Semaphore(ROR_CONCURRENCY)

    def _add(aff: str, match: dict):
        canon = match["canonical"].lower()
        variants = {aff.lower()}
        variants.update(a.lower() for a in match["aliases"] if a)
        variants.update(a.lower() for a in match["acronyms"] if a)
        variants.update(l.lower() for l in match["labels"] if l)
        variants.discard(canon)
        bucket = result.setdefault(canon, [])
        for v in variants:
            if v not in bucket:
                bucket.append(v)

    limits = httpx.Limits(max_connections=ROR_CONCURRENCY,
                          max_keepalive_connections=ROR_CONCURRENCY)
    async with httpx.AsyncClient(timeout=per_request_timeout, limits=limits,
                                 headers={"Accept": "application/json"}) as client:

        async def fetch_one(aff: str):
            async with sem:
                try:
                    match = await asyncio.wait_for(_ror_lookup(client, aff),
                                                   timeout=per_request_timeout + 1)
                except Exception:
                    return
            if match and match.get("canonical"):
                _add(aff, match)

        tasks = [asyncio.create_task(fetch_one(a)) for a in affiliations]
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=overall_cap)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
    return result


# ── LLM fallback ──────────────────────────────────────────────────────────────

async def _llm_expand(
    unresolved: list[str],
    already_canonical: set[str],
) -> dict[str, list[str]]:
    """
    Ask the LLM to group unresolved affiliation strings by institution.
    Returns { canonical → [variants] }
    """
    if not unresolved:
        return {}

    try:
        import llm_provider, json

        affiliations_text = "\n".join(f"- {a}" for a in unresolved[:80])

        system = """You are an expert at identifying research institutions.
Given a list of affiliation strings, group those that refer to the same institution.
Consider abbreviations, language variants, spelling differences, and partial names.

Return ONLY a JSON object (no markdown):
{
  "canonical institution name": ["variant1", "variant2", ...],
  ...
}

Rules:
- Use the full official English name as the canonical key
- Include ALL input strings that match each institution as variants
- Only group strings you are confident refer to the same institution
- If a string is unique and unambiguous, you may omit it
- Lower-case all keys and variants"""

        raw = await llm_provider.call_llm(
            system=system,
            user_text=f"Group these affiliations by institution:\n{affiliations_text}",
            max_tokens=1500,
            task="coi_expand",
        )
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {
                k.lower(): [v.lower() for v in vs if isinstance(v, str)]
                for k, vs in parsed.items()
                if isinstance(vs, list)
            }
    except Exception:
        pass
    return {}


# ── Main entry point ──────────────────────────────────────────────────────────

async def expand_affiliations(
    affiliations: list[str],
    use_ror: bool = True,
    use_llm: bool = True,
    ror_timeout: float = ROR_TIMEOUT,
) -> dict[str, list[str]]:
    """
    Build a synonym dictionary for a set of affiliation strings.

    Args:
        affiliations:  All unique affiliation strings from submissions + TPC files
        use_ror:       Query ROR API (requires internet)
        use_llm:       Use LLM for strings ROR couldn't resolve
        ror_timeout:   Per-request timeout for ROR

    Returns:
        { canonical_name_lower: [variant1_lower, variant2_lower, ...] }
    """
    unique = list({
        a.strip() for a in affiliations
        if a and len(a.strip()) > 3
    })

    synonyms: dict[str, list[str]] = {}
    ror_resolved: set[str] = set()

    # ── Stage 1: ROR ──────────────────────────────────────────────────────────
    if use_ror and unique:
        try:
            # Per-request timeouts + overall cap inside; partial results kept.
            ror_result = await _ror_expand_batch(
                unique, overall_cap=ROR_OVERALL_CAP, per_request_timeout=ror_timeout,
            )
            for canon, variants in ror_result.items():
                if canon not in synonyms:
                    synonyms[canon] = []
                for v in variants:
                    if v not in synonyms[canon]:
                        synonyms[canon].append(v)
                # Track which input affiliations were resolved
                for aff in unique:
                    if aff.lower() in variants or aff.lower() == canon:
                        ror_resolved.add(aff)
        except Exception:
            pass

    # ── Stage 2: LLM fallback for unresolved strings ──────────────────────────
    if use_llm:
        unresolved = [a for a in unique if a not in ror_resolved]
        if unresolved:
            try:
                llm_result = await asyncio.wait_for(
                    _llm_expand(unresolved, set(synonyms.keys())),
                    timeout=20,
                )
                for canon, variants in llm_result.items():
                    if canon not in synonyms:
                        synonyms[canon] = []
                    for v in variants:
                        if v not in synonyms[canon]:
                            synonyms[canon].append(v)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

    return synonyms


def merge_into_checker(expanded: dict[str, list[str]]) -> None:
    """
    Deprecated: no-op. Synonym expansion is now per-request only.
    The expanded dict is passed directly to check_coi via extra_synonyms.
    """
    pass
