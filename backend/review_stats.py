"""
review_stats.py — review statistics, reviewer calibration, track normalisation,
accept/reject recommendations, and 5-tier review quality flagging.
No LLM calls — pure statistics.
"""

import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional


# ── Review quality tiers ──────────────────────────────────────────────────────
# Based on quantitative signals: length, score variance, confidence.
# The AI review quality module adds semantic assessment on top.

QUALITY_TIERS = ["Very Good", "Good", "Average", "Poor", "Unacceptable"]
# Assigned when the review text is not available (empty) — not a quality judgement.
NO_TEXT_TIER = "No text available"


@dataclass
class ReviewQualityFlag:
    review_index: int          # index in review_rows
    paper_id: str
    reviewer_id: str
    tier: str                  # one of QUALITY_TIERS
    signals: list[str]         # human-readable reasons
    score: Optional[float]
    text_length: int
    confidence: Optional[float]


@dataclass
class PaperDecision:
    paper_id: str
    title: str
    track: str
    raw_mean: Optional[float]
    raw_stdev: Optional[float]
    calibrated_mean: Optional[float]   # mean of z-scores normalised to track
    track_percentile: Optional[float]  # 0-100 within track
    review_count: int
    confidence_weighted_mean: Optional[float]
    recommendation: str       # "Strong Accept" / "Accept" / "Borderline" / "Reject" / "Strong Reject"
    confidence_level: str     # "High" / "Medium" / "Low"
    requires_discussion: bool
    discussion_reason: str


@dataclass
class TrackStats:
    track: str
    paper_count: int
    review_count: int
    raw_mean: Optional[float]
    raw_stdev: Optional[float]
    completion_rate: float
    # Reviewer behaviour within this track
    reviewer_means: dict       # reviewer_id → mean score in this track
    reviewer_stdevs: dict      # reviewer_id → stdev in this track


@dataclass
class ReviewStatsReport:
    total_reviews: int
    total_papers: int
    total_reviewers: int
    completion_rate: float
    score_mean: Optional[float]
    score_stdev: Optional[float]
    score_min: Optional[float]
    score_max: Optional[float]
    score_distribution: dict
    tracks: list[TrackStats]
    papers: list[PaperDecision]
    reviewers: list[dict]
    missing_reviews: list[dict]
    overloaded_reviewers: list[dict]
    underloaded_reviewers: list[dict]
    high_variance_papers: list[dict]
    quality_flags: list[ReviewQualityFlag]
    # ── Decision stats from submissions file ──────────────────────────────────
    total_submissions: int = 0
    accepted: int = 0
    rejected: int = 0
    borderline: int = 0          # "accept?", "borderline", "undecided"
    no_decision: int = 0         # empty decision field
    acceptance_rate: Optional[float] = None
    decisions_by_track: list[dict] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(row: dict, *keys) -> str:
    for k in keys:
        for c in [k, k.lower(), k.upper(), k.title()]:
            v = row.get(c)
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _percentile(values: list[float], v: float) -> float:
    """Mid-rank percentile of v within values (0-100).

    Ties count half, so identical values sit at the 50th percentile rather
    than the 0th, and a single-element list yields 50.
    """
    if not values:
        return 50.0
    below = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    return round(((below + 0.5 * equal) / len(values)) * 100, 1)


def _z_score(value: float, mean: float, stdev: float) -> Optional[float]:
    if stdev is None or stdev <= 0:
        return 0.0
    return (value - mean) / stdev


# Minimum number of (non-synthetic) scored reviews a reviewer must have in a
# track before their scores are z-normalised. Below this the stdev is not
# meaningful and the raw score is used instead.
MIN_REVIEWS_FOR_CALIBRATION = 3
# Minimum number of scored papers in a track before percentile-based
# recommendations are produced; below this the scale-relative raw fallback
# is used with Low confidence.
MIN_TRACK_PAPERS_FOR_PERCENTILE = 5

_SCORE_KEYS = ("score", "Score", "overall", "Overall", "grade")
_PAPER_KEYS = ("#", "id", "paper_id", "submission", "Paper", "paper")
_TEXT_KEYS = ("review", "Review", "comments", "Comments", "text", "Text")


def _rev_id(row: dict) -> str:
    return (_get(row, "reviewer", "Reviewer", "reviewer_email", "email", "Email")
            or _get(row, "reviewer_id", "ReviewerID"))


def _score(row: dict) -> Optional[float]:
    return _safe_float(_get(row, *_SCORE_KEYS))


def _is_synthetic(row: dict) -> bool:
    v = row.get("synthetic_reviewer")
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes")
    return bool(v)


def _infer_scale(scores: list[float]) -> tuple[float, float]:
    """Infer the nominal score scale (lo, hi) from observed scores.

    Negative scores -> symmetric scale (EasyChair -3..+3, -2..+2).
    Otherwise lo is 0 or 1 and hi the smallest common scale top >= max.
    """
    if not scores:
        return (1.0, 5.0)
    lo_obs, hi_obs = min(scores), max(scores)
    if lo_obs < 0:
        b = float(math.ceil(max(abs(lo_obs), abs(hi_obs))))
        return (-b, b)
    lo = 0.0 if lo_obs < 1 else 1.0
    for top in (3, 4, 5, 6, 7, 9, 10, 100):
        if hi_obs <= top:
            return (lo, float(top))
    return (lo, float(math.ceil(hi_obs)))


# "poster", "oral", "short paper" etc. are acceptance categories in EasyChair.
_ACCEPT_DEC_RE = re.compile(r'^\s*(accept|accepted|poster|oral|short\s+paper|regular\s+paper|presentation)\b(?!\s*\?)', re.IGNORECASE)
_REJECT_DEC_RE = re.compile(r'^\s*(reject|rejected|desk[\s-]*reject)', re.IGNORECASE)
_BORDER_DEC_RE = re.compile(r'\?\s*$|accept\?|reject\?|borderline|undecided|maybe|tbd|unclear|pending|probabl', re.IGNORECASE)


def _classify_decision(dec: str) -> str:
    """Return 'accept' | 'reject' | 'borderline' | 'none'."""
    dec = (dec or "").strip()
    if not dec:
        return "none"
    if _BORDER_DEC_RE.search(dec):
        return "borderline"
    if _ACCEPT_DEC_RE.match(dec):
        return "accept"
    if _REJECT_DEC_RE.match(dec):
        return "reject"
    return "none"


# ── Review quality flagging ───────────────────────────────────────────────────

def _assess_review_quality(
    review_text: str,
    score: Optional[float],
    confidence: Optional[float],
    all_scores_for_paper: list[float],
    reviewer_mean: Optional[float],
    reviewer_stdev: Optional[float],
) -> tuple[str, list[str]]:
    """
    Assess review quality tier from quantitative signals only.
    Returns (tier, [signals])
    """
    signals = []
    penalty = 0    # higher = worse
    bonus = 0      # higher = better

    text_len = len(review_text.strip()) if review_text else 0

    # ── Text length ────────────────────────────────────────────────────────
    # No text at all means the export did not include it (e.g. EasyChair
    # review_summary) — we cannot judge quality, so don't penalise.
    if text_len == 0:
        return NO_TEXT_TIER, ["No review text available in export — quality not assessed"]
    if text_len < 100:
        penalty += 4
        signals.append(f"Very short ({text_len} chars)")
    elif text_len < 300:
        penalty += 2
        signals.append(f"Short review ({text_len} chars)")
    elif text_len > 1500:
        bonus += 2
    elif text_len > 800:
        bonus += 1

    # ── Confidence ────────────────────────────────────────────────────────
    if confidence is not None:
        if confidence <= 1:
            penalty += 2
            signals.append(f"Very low confidence ({confidence})")
        elif confidence <= 2:
            penalty += 1
            signals.append(f"Low confidence ({confidence})")
        elif confidence >= 4:
            bonus += 1

    # ── Score outlier within paper ─────────────────────────────────────────
    if score is not None and len(all_scores_for_paper) >= 2:
        paper_mean = statistics.mean(all_scores_for_paper)
        paper_stdev = statistics.stdev(all_scores_for_paper)
        if paper_stdev > 0:
            z = abs((score - paper_mean) / paper_stdev)
            if z > 2.0:
                penalty += 2
                signals.append(f"Score is a strong outlier (z={z:.1f}) vs other reviews")
            elif z > 1.5:
                penalty += 1
                signals.append(f"Score is an outlier (z={z:.1f}) vs other reviews")

    # ── Reviewer bias (scores everything high/low) ─────────────────────────
    if reviewer_mean is not None and reviewer_stdev is not None:
        # No penalty for bias itself — it's corrected by calibration
        # But flag extreme lenient/harsh reviewers for transparency
        pass

    # ── Keyword signals in text ────────────────────────────────────────────
    if review_text:
        tl = review_text.lower()
        # Positive signals
        for kw in ["however", "furthermore", "specifically", "in particular",
                   "related work", "contribution", "weakness", "strength",
                   "section", "figure", "equation", "experiment", "result"]:
            if kw in tl:
                bonus += 0.3
        # Negative signals
        for kw in ["no comment", "no review", "n/a", "see above",
                   "i agree", "same as"]:
            if kw in tl:
                penalty += 1.5
                signals.append(f'Suspicious phrase: "{kw}"')

    # ── Map to tier ────────────────────────────────────────────────────────
    net = bonus - penalty
    if net >= 2:
        tier = "Very Good"
    elif net >= 0:
        tier = "Good"
    elif net >= -2:
        tier = "Average"
    elif net >= -4:
        tier = "Poor"
    else:
        tier = "Unacceptable"

    return tier, signals


# ── Main function ─────────────────────────────────────────────────────────────

def compute_stats(
    review_rows: list[dict],
    submission_rows: list[dict],
    assignment_rows: list[dict] = None,
    min_reviews_per_paper: int = 3,
    max_load_per_reviewer: int = 8,
    min_load_per_reviewer: int = 1,
    high_variance_threshold: float = 1.5,
    accept_threshold_pct: float = 65.0,   # top X% of calibrated scores → accept
    reject_threshold_pct: float = 35.0,   # bottom X% → reject
) -> ReviewStatsReport:

    submission_rows = submission_rows or []
    assignment_rows = assignment_rows or []

    # ── Index submissions ──────────────────────────────────────────────────
    sub_by_id: dict[str, dict] = {}
    for row in submission_rows:
        pid = _get(row, "#", "id", "paper_id", "submission_id")
        if pid:
            sub_by_id[pid] = row

    # ── Group reviews by paper and reviewer ───────────────────────────────
    # Rows with neither a reviewer nor a score are paper placeholders (e.g. a
    # review_summary line for a paper with no reviews yet): they register the
    # paper but are not counted as reviews.
    reviews_by_paper: dict[str, list[dict]] = {}
    reviews_by_reviewer: dict[str, list[dict]] = {}
    review_meta: dict[str, dict] = {}       # pid → first review row (title/track fallback)
    real_reviews: list[dict] = []
    all_scores: list[float] = []

    for row in review_rows:
        pid = _get(row, *_PAPER_KEYS)
        rev = _rev_id(row)
        s = _score(row)
        if pid and pid not in review_meta:
            review_meta[pid] = row
        if not rev and s is None and not _get(row, *_TEXT_KEYS):
            continue  # placeholder, not a review
        real_reviews.append(row)
        if pid:
            reviews_by_paper.setdefault(pid, []).append(row)
        if rev:
            reviews_by_reviewer.setdefault(rev, []).append(row)
        if s is not None:
            all_scores.append(s)

    scale_lo, scale_hi = _infer_scale(all_scores)
    scale_mid = (scale_lo + scale_hi) / 2.0
    scale_span = (scale_hi - scale_lo) or 1.0

    def _track_of(pid: str) -> str:
        return (_get(sub_by_id.get(pid, {}), "track", "Track")
                or _get(review_meta.get(pid, {}), "track", "Track")
                or "Unassigned")

    def _title_of(pid: str) -> str:
        return (_get(sub_by_id.get(pid, {}), "title", "Title")
                or _get(review_meta.get(pid, {}), "title", "Title"))

    # Universe of papers: every submission plus anything that appears in reviews.
    all_pids: list[str] = list(sub_by_id.keys())
    for pid in list(review_meta.keys()) + list(reviews_by_paper.keys()):
        if pid not in sub_by_id and pid not in all_pids:
            all_pids.append(pid)

    # ── Per-track grouping ─────────────────────────────────────────────────
    papers_by_track: dict[str, list[str]] = {}
    for pid in all_pids:
        papers_by_track.setdefault(_track_of(pid), []).append(pid)

    # ── Reviewer calibration: mean/stdev per reviewer per track ───────────
    # Synthetic reviewers (per-paper placeholder IDs) are never calibrated.
    reviewer_scores_by_track: dict[str, dict[str, list[float]]] = {}
    for pid, rvs in reviews_by_paper.items():
        track = _track_of(pid)
        for rv in rvs:
            rev_id = _rev_id(rv)
            s = _score(rv)
            if rev_id and s is not None and not _is_synthetic(rv):
                reviewer_scores_by_track.setdefault(track, {}).setdefault(rev_id, []).append(s)

    # Only reviewers with enough reviews get calibration stats.
    reviewer_stats_by_track: dict[str, dict[str, dict]] = {}
    for track, rev_map in reviewer_scores_by_track.items():
        reviewer_stats_by_track[track] = {}
        for rev_id, scores in rev_map.items():
            if len(scores) < MIN_REVIEWS_FOR_CALIBRATION:
                continue
            m = statistics.mean(scores)
            sd = statistics.stdev(scores)
            reviewer_stats_by_track[track][rev_id] = {
                "mean": m, "stdev": sd, "n": len(scores),
            }

    # Track-level raw distribution (used to put uncalibrated raw scores on
    # the same z-like footing as calibrated ones).
    track_raw: dict[str, tuple[float, float]] = {}
    for track, pids in papers_by_track.items():
        ts = [s for pid in pids for s in (_score(r) for r in reviews_by_paper.get(pid, [])) if s is not None]
        if ts:
            track_raw[track] = (statistics.mean(ts), statistics.stdev(ts) if len(ts) >= 2 else 0.0)

    # ── Per-paper ranking score ───────────────────────────────────────────
    # Each review contributes the reviewer's z-score when the reviewer is
    # calibratable (≥ MIN_REVIEWS_FOR_CALIBRATION real reviews in the track,
    # non-zero stdev), otherwise its raw score standardised against the
    # track's raw distribution. calibrated_mean is reported only when at
    # least one review was reviewer-calibrated.
    paper_rank_score: dict[str, float] = {}
    paper_calibrated: dict[str, float] = {}
    paper_cal_count: dict[str, int] = {}
    paper_raw_scores: dict[str, list[float]] = {}

    for pid, rvs in reviews_by_paper.items():
        track = _track_of(pid)
        rev_stats = reviewer_stats_by_track.get(track, {})
        t_mean, t_sd = track_raw.get(track, (0.0, 0.0))

        vals: list[float] = []
        raw_scores: list[float] = []
        n_cal = 0
        for rv in rvs:
            s = _score(rv)
            if s is None:
                continue
            raw_scores.append(s)
            rs = None if _is_synthetic(rv) else rev_stats.get(_rev_id(rv))
            if rs and rs["stdev"] > 0:
                vals.append(_z_score(s, rs["mean"], rs["stdev"]))
                n_cal += 1
            else:
                vals.append(_z_score(s, t_mean, t_sd))

        paper_raw_scores[pid] = raw_scores
        paper_cal_count[pid] = n_cal
        if vals:
            paper_rank_score[pid] = statistics.mean(vals)
            if n_cal > 0:
                paper_calibrated[pid] = paper_rank_score[pid]

    # ── Per-track ranking-score distribution ──────────────────────────────
    track_rank_scores: dict[str, list[float]] = {}
    for pid, sc in paper_rank_score.items():
        track_rank_scores.setdefault(_track_of(pid), []).append(sc)

    # Scale-relative raw thresholds (EasyChair -3..+3 → ±0.75; 1..5 → 3.5/2.5)
    raw_accept_thr = scale_mid + scale_span / 8.0
    raw_reject_thr = scale_mid - scale_span / 8.0

    # ── Recommendations per paper ─────────────────────────────────────────
    paper_decisions: list[PaperDecision] = []
    missing_reviews: list[dict] = []
    high_variance_papers: list[dict] = []

    for pid in all_pids:
        rvs = reviews_by_paper.get(pid, [])
        title = _title_of(pid)
        track = _track_of(pid)
        raw_scores = paper_raw_scores.get(pid, [])

        raw_mean = statistics.mean(raw_scores) if raw_scores else None
        raw_stdev = statistics.stdev(raw_scores) if len(raw_scores) >= 2 else None
        cal_score = paper_calibrated.get(pid)
        rank_score = paper_rank_score.get(pid)
        track_scores = track_rank_scores.get(track, [])
        track_has_variance = len(set(round(x, 9) for x in track_scores)) > 1
        percentile_usable = (
            rank_score is not None
            and len(track_scores) >= MIN_TRACK_PAPERS_FOR_PERCENTILE
            and track_has_variance
        )
        percentile = (_percentile(track_scores, rank_score)
                      if rank_score is not None and track_scores else None)

        # Confidence-weighted mean
        conf_weighted = None
        weighted_sum = 0.0
        weight_total = 0.0
        for rv in rvs:
            s = _score(rv)
            c = _safe_float(_get(rv, "confidence", "Confidence"))
            if s is not None and c is not None and c > 0:
                weighted_sum += s * c
                weight_total += c
        if weight_total > 0:
            conf_weighted = round(weighted_sum / weight_total, 2)

        requires_discussion = False
        discussion_reason = ""
        confidence_level = "Medium"
        fully_calibrated = bool(raw_scores) and paper_cal_count.get(pid, 0) == len(raw_scores)

        if percentile_usable and percentile is not None:
            if percentile >= accept_threshold_pct:
                if raw_stdev is not None and raw_stdev >= high_variance_threshold:
                    recommendation = "Borderline"
                    requires_discussion = True
                    discussion_reason = f"Top {100-accept_threshold_pct:.0f}% score in track but high variance (σ={raw_stdev:.1f})"
                    confidence_level = "Low"
                else:
                    recommendation = "Strong Accept" if percentile >= 85 else "Accept"
                    confidence_level = "High" if percentile >= 80 else "Medium"
            elif percentile <= reject_threshold_pct:
                recommendation = "Strong Reject" if percentile <= 15 else "Reject"
                confidence_level = "High" if percentile <= 20 else "Medium"
            else:
                recommendation = "Borderline"
                requires_discussion = True
                discussion_reason = f"Score at {percentile:.0f}th percentile in track"
                confidence_level = "Low"
            # Without proper reviewer calibration, don't claim high confidence
            if confidence_level == "High" and not fully_calibrated:
                confidence_level = "Medium"
            if len(raw_scores) < 2 and confidence_level != "Low":
                confidence_level = "Low"
        elif raw_mean is not None:
            # Fallback: scale-relative thresholds on raw mean (too few papers
            # in the track, or no score variance to rank on).
            if raw_mean >= raw_accept_thr:
                recommendation = "Accept"
            elif raw_mean < raw_reject_thr:
                recommendation = "Reject"
            else:
                recommendation = "Borderline"
            requires_discussion = recommendation == "Borderline"
            if requires_discussion:
                discussion_reason = (f"Raw mean {raw_mean:.2f} near scale midpoint "
                                     f"({scale_lo:g}..{scale_hi:g})")
            confidence_level = "Low"
        else:
            recommendation = "Insufficient data"
            confidence_level = "Low"

        # High variance flag
        if raw_stdev is not None and raw_stdev >= high_variance_threshold:
            high_variance_papers.append({
                "id": pid, "title": title, "track": track,
                "score_stdev": round(raw_stdev, 2),
                "score_min": min(raw_scores), "score_max": max(raw_scores),
                "review_count": len(rvs),
            })

        # Missing reviews (includes papers with zero reviews)
        if len(rvs) < min_reviews_per_paper:
            missing_reviews.append({
                "id": pid, "title": title, "track": track,
                "review_count": len(rvs),
                "needed": min_reviews_per_paper - len(rvs),
                "no_reviews": len(rvs) == 0,
            })

        paper_decisions.append(PaperDecision(
            paper_id=pid, title=title, track=track,
            raw_mean=round(raw_mean, 2) if raw_mean is not None else None,
            raw_stdev=round(raw_stdev, 2) if raw_stdev is not None else None,
            calibrated_mean=round(cal_score, 3) if cal_score is not None else None,
            track_percentile=percentile,
            review_count=len(rvs),
            confidence_weighted_mean=conf_weighted,
            recommendation=recommendation,
            confidence_level=confidence_level,
            requires_discussion=requires_discussion,
            discussion_reason=discussion_reason,
        ))

    # Zero-review papers first, then fewest reviews.
    missing_reviews.sort(key=lambda m: (m["review_count"], str(m["id"])))

    # ── Review quality flagging ───────────────────────────────────────────
    quality_flags: list[ReviewQualityFlag] = []

    for idx, rv in enumerate(review_rows):
        pid = _get(rv, *_PAPER_KEYS)
        rev_id = _rev_id(rv)
        score = _score(rv)
        if not rev_id and score is None and not _get(rv, *_TEXT_KEYS):
            continue  # placeholder row, not a review
        confidence = _safe_float(_get(rv, "confidence", "Confidence"))
        text = _get(rv, *_TEXT_KEYS)

        track = _track_of(pid)
        all_paper_scores = [s for s in (_score(r) for r in reviews_by_paper.get(pid, [])) if s is not None]

        rev_stats_t = reviewer_stats_by_track.get(track, {}).get(rev_id, {})
        rev_mean = rev_stats_t.get("mean")
        rev_stdev = rev_stats_t.get("stdev")

        tier, signals = _assess_review_quality(
            text, score, confidence,
            all_paper_scores, rev_mean, rev_stdev
        )

        quality_flags.append(ReviewQualityFlag(
            review_index=idx,
            paper_id=pid,
            reviewer_id=rev_id,
            tier=tier,
            signals=signals,
            score=score,
            text_length=len(text.strip()) if text else 0,
            confidence=confidence,
        ))

    # ── Assignments (optional): who was assigned what ─────────────────────
    assigned_by_reviewer: dict[str, set] = {}
    for row in assignment_rows:
        rev = (_rev_id(row) or _get(row, "member", "Member", "PC member", "pc_member", "name", "Name"))
        pid = _get(row, *_PAPER_KEYS)
        if rev:
            assigned_by_reviewer.setdefault(rev, set())
            if pid:
                assigned_by_reviewer[rev].add(pid)

    # ── Per-reviewer summary ──────────────────────────────────────────────
    reviewer_summary = []
    overloaded = []
    underloaded = []

    flags_by_rev: dict[str, list[ReviewQualityFlag]] = {}
    for f in quality_flags:
        flags_by_rev.setdefault(f.reviewer_id, []).append(f)

    all_reviewers = list(reviews_by_reviewer.keys()) + [
        r for r in assigned_by_reviewer if r not in reviews_by_reviewer
    ]
    for rev in all_reviewers:
        rvs = reviews_by_reviewer.get(rev, [])
        scores = [s for s in (_score(r) for r in rvs) if s is not None]
        mean_score = statistics.mean(scores) if scores else None
        flags_for_rev = flags_by_rev.get(rev, [])
        tier_counts = {t: sum(1 for f in flags_for_rev if f.tier == t) for t in QUALITY_TIERS}
        no_text = sum(1 for f in flags_for_rev if f.tier == NO_TEXT_TIER)
        if no_text:
            tier_counts[NO_TEXT_TIER] = no_text
        assigned = len(assigned_by_reviewer.get(rev, ()))

        entry = {
            "id": rev,
            "review_count": len(rvs),
            "mean_score_given": round(mean_score, 2) if mean_score is not None else None,
            "quality_tier_counts": tier_counts,
            "synthetic": bool(rvs) and all(_is_synthetic(r) for r in rvs),
        }
        if assigned_by_reviewer:
            entry["assigned_count"] = assigned
        reviewer_summary.append(entry)

        # Synthetic per-paper reviewer IDs carry no load information.
        if rvs and all(_is_synthetic(r) for r in rvs):
            continue
        load = max(len(rvs), assigned)
        if load > max_load_per_reviewer:
            overloaded.append({"id": rev, "count": load})
        # Load counts assigned papers too, so reviewers who appear only in the
        # assignments file (0 completed reviews) are caught.
        if load < min_load_per_reviewer or (assigned and len(rvs) == 0):
            underloaded.append({"id": rev, "count": len(rvs), "assigned": assigned})

    # ── Per-track stats ───────────────────────────────────────────────────
    track_stats_list = []
    for track, pids in papers_by_track.items():
        track_reviews = [rv for pid in pids for rv in reviews_by_paper.get(pid, [])]
        track_scores = [s for s in (_score(r) for r in track_reviews) if s is not None]
        rev_stats = reviewer_stats_by_track.get(track, {})
        expected = len(pids) * min_reviews_per_paper
        completion = round(len(track_reviews) / expected * 100, 1) if expected > 0 else 0.0

        track_stats_list.append(TrackStats(
            track=track,
            paper_count=len(pids),
            review_count=len(track_reviews),
            raw_mean=round(statistics.mean(track_scores), 2) if track_scores else None,
            raw_stdev=round(statistics.stdev(track_scores), 2) if len(track_scores) >= 2 else None,
            completion_rate=completion,
            reviewer_means={r: round(s["mean"], 2) for r, s in rev_stats.items()},
            reviewer_stdevs={r: round(s["stdev"], 2) for r, s in rev_stats.items()},
        ))

    # ── Score distribution ────────────────────────────────────────────────
    score_dist = {}
    for s in all_scores:
        b = str(round(s))
        score_dist[b] = score_dist.get(b, 0) + 1

    # ── Decision stats from submissions file ─────────────────────────────────
    accepted = rejected = borderline = no_decision = 0
    decisions_by_track: dict[str, dict] = {}

    for row in submission_rows:
        dec = _get(row, "decision", "Decision", "DECISION", "status", "Status") or ""
        track = _get(row, "track", "Track") or "Unassigned"

        if track not in decisions_by_track:
            decisions_by_track[track] = {
                "track": track, "total": 0,
                "accepted": 0, "rejected": 0,
                "borderline": 0, "no_decision": 0,
                "acceptance_rate": None,
            }
        decisions_by_track[track]["total"] += 1

        kind = _classify_decision(dec)
        if kind == "accept":
            accepted += 1
            decisions_by_track[track]["accepted"] += 1
        elif kind == "reject":
            rejected += 1
            decisions_by_track[track]["rejected"] += 1
        elif kind == "borderline":
            borderline += 1
            decisions_by_track[track]["borderline"] += 1
        else:
            no_decision += 1
            decisions_by_track[track]["no_decision"] += 1

    # Compute per-track acceptance rates
    for td in decisions_by_track.values():
        decided = td["accepted"] + td["rejected"]
        td["acceptance_rate"] = (
            round(td["accepted"] / decided * 100, 1) if decided > 0 else None
        )

    total_submissions = len(submission_rows)
    decided_total = accepted + rejected
    acceptance_rate = (
        round(accepted / decided_total * 100, 1) if decided_total > 0 else None
    )

    # ── Completion rate ───────────────────────────────────────────────────
    expected_total = len(all_pids) * min_reviews_per_paper
    completion = round(len(real_reviews) / expected_total * 100, 1) if expected_total > 0 else 0.0

    def _sort_key(p: PaperDecision) -> float:
        if p.calibrated_mean is not None:
            return p.calibrated_mean
        rs = paper_rank_score.get(p.paper_id)
        if rs is not None:
            return rs
        return float("-inf")

    report = ReviewStatsReport(
        total_reviews=len(real_reviews),
        total_papers=len(reviews_by_paper),
        total_reviewers=len(reviews_by_reviewer),
        completion_rate=completion,
        score_mean=round(statistics.mean(all_scores), 2) if all_scores else None,
        score_stdev=round(statistics.stdev(all_scores), 2) if len(all_scores) >= 2 else None,
        score_min=min(all_scores) if all_scores else None,
        score_max=max(all_scores) if all_scores else None,
        score_distribution=score_dist,
        tracks=track_stats_list,
        papers=sorted(paper_decisions, key=_sort_key, reverse=True),
        reviewers=reviewer_summary,
        missing_reviews=missing_reviews,
        overloaded_reviewers=overloaded,
        underloaded_reviewers=underloaded,
        high_variance_papers=high_variance_papers,
        quality_flags=quality_flags,
        total_submissions=total_submissions,
        accepted=accepted,
        rejected=rejected,
        borderline=borderline,
        no_decision=no_decision,
        acceptance_rate=acceptance_rate,
        decisions_by_track=sorted(decisions_by_track.values(), key=lambda x: x["track"]),
    )
    # Extra (non-dataclass) info exposed by report_to_dict
    report.score_scale = (scale_lo, scale_hi)
    report.papers_without_reviews = sum(1 for m in missing_reviews if m["review_count"] == 0)
    report.calibrated_reviewers = sum(len(v) for v in reviewer_stats_by_track.values())
    return report


def report_to_dict(r: ReviewStatsReport) -> dict:
    return {
        "total_reviews": r.total_reviews,
        "total_papers": r.total_papers,
        "total_reviewers": r.total_reviewers,
        "completion_rate": r.completion_rate,
        "score_mean": r.score_mean,
        "score_stdev": r.score_stdev,
        "score_min": r.score_min,
        "score_max": r.score_max,
        "score_distribution": r.score_distribution,
        "tracks": [{
            "track": t.track,
            "paper_count": t.paper_count,
            "review_count": t.review_count,
            "mean_score": t.raw_mean,
            "stdev_score": t.raw_stdev,
            "completion_rate": t.completion_rate,
            "reviewer_means": t.reviewer_means,
        } for t in r.tracks],
        "papers": [{
            "id": p.paper_id,
            "title": p.title,
            "track": p.track,
            "raw_mean": p.raw_mean,
            "raw_stdev": p.raw_stdev,
            "calibrated_mean": p.calibrated_mean,
            "track_percentile": p.track_percentile,
            "review_count": p.review_count,
            "confidence_weighted_mean": p.confidence_weighted_mean,
            "recommendation": p.recommendation,
            "confidence_level": p.confidence_level,
            "requires_discussion": p.requires_discussion,
            "discussion_reason": p.discussion_reason,
        } for p in r.papers],
        "reviewers": r.reviewers,
        "missing_reviews": r.missing_reviews,
        "overloaded_reviewers": r.overloaded_reviewers,
        "underloaded_reviewers": r.underloaded_reviewers,
        "high_variance_papers": r.high_variance_papers,
        "quality_flags": [{
            "review_index": f.review_index,
            "paper_id": f.paper_id,
            "reviewer_id": f.reviewer_id,
            "tier": f.tier,
            "signals": f.signals,
            "score": f.score,
            "text_length": f.text_length,
            "confidence": f.confidence,
        } for f in r.quality_flags],
        "total_submissions": r.total_submissions,
        "accepted": r.accepted,
        "rejected": r.rejected,
        "borderline": r.borderline,
        "no_decision": r.no_decision,
        "acceptance_rate": r.acceptance_rate,
        "decisions_by_track": r.decisions_by_track,
        "score_scale": list(getattr(r, "score_scale", (None, None))),
        "papers_without_reviews": getattr(r, "papers_without_reviews", 0),
        "calibrated_reviewers": getattr(r, "calibrated_reviewers", 0),
    }
