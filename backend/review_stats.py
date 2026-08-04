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
    """Return what percentile v is in the list of values (0-100)."""
    if not values:
        return 50.0
    below = sum(1 for x in values if x < v)
    return round((below / len(values)) * 100, 1)


def _z_score(value: float, mean: float, stdev: float) -> Optional[float]:
    if stdev == 0:
        return 0.0
    return (value - mean) / stdev


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

    # ── Index submissions ──────────────────────────────────────────────────
    sub_by_id: dict[str, dict] = {}
    for row in submission_rows:
        pid = _get(row, "#", "id", "paper_id", "submission_id")
        if pid:
            sub_by_id[pid] = row

    # ── Group reviews by paper and reviewer ───────────────────────────────
    reviews_by_paper: dict[str, list[dict]] = {}
    reviews_by_reviewer: dict[str, list[dict]] = {}
    all_scores: list[float] = []

    for row in review_rows:
        pid = _get(row, "#", "id", "paper_id", "submission", "Paper", "paper")
        rev = (_get(row, "reviewer", "Reviewer", "reviewer_email", "email", "Email")
               or _get(row, "reviewer_id", "ReviewerID"))
        if pid:
            reviews_by_paper.setdefault(pid, []).append(row)
        if rev:
            reviews_by_reviewer.setdefault(rev, []).append(row)
        s = _safe_float(_get(row, "score", "Score", "overall", "Overall", "grade"))
        if s is not None:
            all_scores.append(s)

    # ── Per-track grouping ─────────────────────────────────────────────────
    papers_by_track: dict[str, list[str]] = {}
    for pid, meta in sub_by_id.items():
        track = _get(meta, "track", "Track") or "Unassigned"
        papers_by_track.setdefault(track, []).append(pid)

    # ── Reviewer calibration: mean/stdev per reviewer per track ───────────
    # Structure: { track → { reviewer_id → [scores] } }
    reviewer_scores_by_track: dict[str, dict[str, list[float]]] = {}

    for pid, rvs in reviews_by_paper.items():
        meta = sub_by_id.get(pid, {})
        track = _get(meta, "track", "Track") or "Unassigned"
        for rv in rvs:
            rev_id = (_get(rv, "reviewer", "Reviewer", "reviewer_email", "email", "Email")
                      or _get(rv, "reviewer_id", "ReviewerID"))
            s = _safe_float(_get(rv, "score", "Score", "overall", "Overall", "grade"))
            if rev_id and s is not None:
                reviewer_scores_by_track.setdefault(track, {}).setdefault(rev_id, []).append(s)

    # Compute reviewer mean/stdev per track
    reviewer_stats_by_track: dict[str, dict[str, dict]] = {}
    for track, rev_map in reviewer_scores_by_track.items():
        reviewer_stats_by_track[track] = {}
        for rev_id, scores in rev_map.items():
            m = statistics.mean(scores)
            sd = statistics.stdev(scores) if len(scores) >= 2 else 1.0
            reviewer_stats_by_track[track][rev_id] = {"mean": m, "stdev": max(sd, 0.01)}

    # ── Compute calibrated scores per paper ───────────────────────────────
    # For each review, compute z-score relative to reviewer's track behaviour.
    # Calibrated paper score = mean of reviewer z-scores.
    paper_calibrated: dict[str, float] = {}
    paper_raw_scores: dict[str, list[float]] = {}

    for pid, rvs in reviews_by_paper.items():
        meta = sub_by_id.get(pid, {})
        track = _get(meta, "track", "Track") or "Unassigned"
        rev_stats = reviewer_stats_by_track.get(track, {})

        z_scores = []
        raw_scores = []
        for rv in rvs:
            rev_id = (_get(rv, "reviewer", "Reviewer", "reviewer_email", "email", "Email")
                      or _get(rv, "reviewer_id", "ReviewerID"))
            s = _safe_float(_get(rv, "score", "Score", "overall", "Overall", "grade"))
            if s is not None:
                raw_scores.append(s)
                rs = rev_stats.get(rev_id)
                if rs:
                    z = _z_score(s, rs["mean"], rs["stdev"])
                    if z is not None:
                        z_scores.append(z)

        paper_raw_scores[pid] = raw_scores
        if z_scores:
            paper_calibrated[pid] = statistics.mean(z_scores)

    # ── Per-track calibrated score distribution ───────────────────────────
    track_calibrated_scores: dict[str, list[float]] = {}
    for pid, cal_score in paper_calibrated.items():
        meta = sub_by_id.get(pid, {})
        track = _get(meta, "track", "Track") or "Unassigned"
        track_calibrated_scores.setdefault(track, []).append(cal_score)

    # ── Recommendations per paper ─────────────────────────────────────────
    paper_decisions: list[PaperDecision] = []
    missing_reviews: list[dict] = []
    high_variance_papers: list[dict] = []

    for pid, rvs in reviews_by_paper.items():
        meta = sub_by_id.get(pid, {})
        title = _get(meta, "title", "Title")
        track = _get(meta, "track", "Track") or "Unassigned"
        raw_scores = paper_raw_scores.get(pid, [])

        raw_mean = statistics.mean(raw_scores) if raw_scores else None
        raw_stdev = statistics.stdev(raw_scores) if len(raw_scores) >= 2 else None
        cal_score = paper_calibrated.get(pid)
        track_scores = track_calibrated_scores.get(track, [])
        percentile = _percentile(track_scores, cal_score) if cal_score is not None and track_scores else None

        # Confidence-weighted mean
        conf_weighted = None
        weighted_sum = 0.0
        weight_total = 0.0
        for rv in rvs:
            s = _safe_float(_get(rv, "score", "Score", "overall", "Overall", "grade"))
            c = _safe_float(_get(rv, "confidence", "Confidence"))
            if s is not None and c is not None:
                weighted_sum += s * c
                weight_total += c
        if weight_total > 0:
            conf_weighted = round(weighted_sum / weight_total, 2)

        # Recommendation based on calibrated percentile within track
        requires_discussion = False
        discussion_reason = ""
        confidence_level = "Medium"

        if percentile is not None:
            if percentile >= accept_threshold_pct:
                if raw_stdev is not None and raw_stdev >= high_variance_threshold:
                    recommendation = "Borderline"
                    requires_discussion = True
                    discussion_reason = f"Top {100-accept_threshold_pct:.0f}% calibrated score but high variance (σ={raw_stdev:.1f})"
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
                discussion_reason = f"Calibrated score at {percentile:.0f}th percentile in track"
                confidence_level = "Low"
        elif raw_mean is not None:
            # Fallback: use raw scores if calibration unavailable
            recommendation = "Accept" if raw_mean >= 3.5 else ("Reject" if raw_mean < 2.5 else "Borderline")
            requires_discussion = recommendation == "Borderline"
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

        # Missing reviews
        if len(rvs) < min_reviews_per_paper:
            missing_reviews.append({
                "id": pid, "title": title, "track": track,
                "review_count": len(rvs),
                "needed": min_reviews_per_paper - len(rvs),
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

    # ── Review quality flagging ───────────────────────────────────────────
    quality_flags: list[ReviewQualityFlag] = []

    for idx, rv in enumerate(review_rows):
        pid = _get(rv, "#", "id", "paper_id", "submission", "Paper", "paper")
        rev_id = (_get(rv, "reviewer", "Reviewer", "reviewer_email", "email", "Email")
                  or _get(rv, "reviewer_id", "ReviewerID"))
        score = _safe_float(_get(rv, "score", "Score", "overall", "Overall", "grade"))
        confidence = _safe_float(_get(rv, "confidence", "Confidence"))
        text = _get(rv, "review", "Review", "comments", "Comments", "text", "Text")

        meta = sub_by_id.get(pid, {})
        track = _get(meta, "track", "Track") or "Unassigned"
        all_paper_scores = [
            s for s in [
                _safe_float(_get(r, "score", "Score", "overall", "Overall", "grade"))
                for r in reviews_by_paper.get(pid, [])
            ] if s is not None
        ]

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

    # ── Per-reviewer summary ──────────────────────────────────────────────
    reviewer_summary = []
    overloaded = []
    underloaded = []

    for rev, rvs in reviews_by_reviewer.items():
        scores = [s for s in [
            _safe_float(_get(r, "score", "Score", "overall", "Overall", "grade"))
            for r in rvs
        ] if s is not None]
        mean_score = statistics.mean(scores) if scores else None
        flags_for_rev = [f for f in quality_flags if f.reviewer_id == rev]
        tier_counts = {t: sum(1 for f in flags_for_rev if f.tier == t) for t in QUALITY_TIERS}

        reviewer_summary.append({
            "id": rev,
            "review_count": len(rvs),
            "mean_score_given": round(mean_score, 2) if mean_score is not None else None,
            "quality_tier_counts": tier_counts,
        })

        if len(rvs) > max_load_per_reviewer:
            overloaded.append({"id": rev, "count": len(rvs)})
        if len(rvs) < min_load_per_reviewer:
            underloaded.append({"id": rev, "count": len(rvs)})

    # ── Per-track stats ───────────────────────────────────────────────────
    track_stats_list = []
    for track, pids in papers_by_track.items():
        track_reviews = [rv for pid in pids for rv in reviews_by_paper.get(pid, [])]
        track_scores = [s for s in [
            _safe_float(_get(r, "score", "Score", "overall", "Overall", "grade"))
            for r in track_reviews
        ] if s is not None]
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

    _ACCEPT_RE = re.compile(r'^\s*accept\s*$', re.IGNORECASE)
    _REJECT_RE = re.compile(r'^\s*reject\s*$', re.IGNORECASE)
    _BORDER_RE = re.compile(r'accept\?|borderline|undecided|maybe|tbd|unclear', re.IGNORECASE)

    for row in submission_rows:
        dec_raw = _get(row, "decision", "Decision", "DECISION", "status", "Status") or ""
        dec = dec_raw.strip()
        track = _get(row, "track", "Track") or "Unassigned"

        if track not in decisions_by_track:
            decisions_by_track[track] = {
                "track": track, "total": 0,
                "accepted": 0, "rejected": 0,
                "borderline": 0, "no_decision": 0,
                "acceptance_rate": None,
            }
        decisions_by_track[track]["total"] += 1

        if _ACCEPT_RE.match(dec):
            accepted += 1
            decisions_by_track[track]["accepted"] += 1
        elif _REJECT_RE.match(dec):
            rejected += 1
            decisions_by_track[track]["rejected"] += 1
        elif _BORDER_RE.search(dec):
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
    expected_total = len(sub_by_id) * min_reviews_per_paper if sub_by_id else len(reviews_by_paper) * min_reviews_per_paper
    completion = round(len(review_rows) / expected_total * 100, 1) if expected_total > 0 else 0.0

    return ReviewStatsReport(
        total_reviews=len(review_rows),
        total_papers=len(reviews_by_paper),
        total_reviewers=len(reviews_by_reviewer),
        completion_rate=completion,
        score_mean=round(statistics.mean(all_scores), 2) if all_scores else None,
        score_stdev=round(statistics.stdev(all_scores), 2) if len(all_scores) >= 2 else None,
        score_min=min(all_scores) if all_scores else None,
        score_max=max(all_scores) if all_scores else None,
        score_distribution=score_dist,
        tracks=track_stats_list,
        papers=sorted(paper_decisions, key=lambda p: p.calibrated_mean or p.raw_mean or 0, reverse=True),
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
    }
