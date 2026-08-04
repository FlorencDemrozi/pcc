"""
affiliation_expander.py — automatic synonym expansion for institution affiliations.

Two-stage pipeline:
  1. ROR (Research Organization Registry) — free, no key, 100k+ institutions
  2. LLM fallback — for abbreviations, misspellings, informal names ROR misses

Call expand_affiliations(affiliation_strings) once before the COI check.
Returns a dict: { canonical_name: [variant1, variant2, ...] }
"""

import asyncio
import re
from typing import Optional
import httpx


# ── ROR API ───────────────────────────────────────────────────────────────────

ROR_API = "https://api.ror.org/organizations"
ROR_TIMEOUT = 8.0      # seconds per request
ROR_CONCURRENCY = 5    # max parallel requests


def _clean_affiliation(aff: str) -> str:
    """Normalise an affiliation string for lookup."""
    # Remove department/lab prefixes that confuse ROR
    aff = re.sub(
        r'(?i)^(dept\.?|department of|lab(?:oratory)? of|school of|'
        r'faculty of|institute of|center for|centre for)\s+\S+\s*,?\s*',
        '', aff
    ).strip()
    # Remove trailing country/city if comma-separated
    parts = [p.strip() for p in aff.split(',')]
    # Keep longest meaningful part
    return max(parts, key=len) if parts else aff


async def _ror_lookup(client: httpx.AsyncClient, affiliation: str) -> Optional[dict]:
    """
    Query ROR for a single affiliation string.
    Returns the best match or None.
    """
    query = _clean_affiliation(affiliation)
    if len(query) < 4:
        return None
    try:
        r = await client.get(
            ROR_API,
            params={"affiliation": query},
            timeout=ROR_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("items", [])
        if not items:
            return None
        # Take the top result if confidence is high enough
        best = items[0]
        score = best.get("score", 0)
        chosen = best.get("chosen", False)
        if score >= 0.8 or chosen:
            org = best.get("organization", {})
            return {
                "canonical": org.get("name", ""),
                "aliases":   org.get("aliases", []),
                "acronyms":  org.get("acronyms", []),
                "labels":    [l.get("label", "") for l in org.get("labels", [])],
                "score":     score,
            }
    except Exception:
        pass
    return None


async def _ror_expand_batch(affiliations: list[str]) -> dict[str, list[str]]:
    """
    Query ROR for all unique affiliations concurrently.
    Returns { canonical → [variants] }
    """
    result: dict[str, list[str]] = {}
    sem = asyncio.Semaphore(ROR_CONCURRENCY)

    async def fetch_one(aff: str):
        async with sem:
            async with httpx.AsyncClient() as client:
                match = await _ror_lookup(client, aff)
            if match and match["canonical"]:
                canon = match["canonical"].lower()
                variants = set()
                variants.add(aff.lower())
                variants.update(a.lower() for a in match["aliases"] if a)
                variants.update(a.lower() for a in match["acronyms"] if a)
                variants.update(l.lower() for l in match["labels"] if l)
                variants.discard(canon)
                if canon not in result:
                    result[canon] = []
                for v in variants:
                    if v not in result[canon]:
                        result[canon].append(v)

    await asyncio.gather(*[fetch_one(aff) for aff in affiliations])
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
            ror_result = await asyncio.wait_for(
                _ror_expand_batch(unique),
                timeout=min(ror_timeout * len(unique) / ROR_CONCURRENCY + 5, 30)
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
        except asyncio.TimeoutError:
            pass  # ROR timed out — fall through to LLM
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
