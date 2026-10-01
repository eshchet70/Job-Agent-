"""
Heuristic Strategic Fit estimator.
Maps parsed JD signals to dimension scores without requiring LLM output.
This is the deterministic fallback; an LLM adapter can override scores.
"""
from __future__ import annotations

from app.models import (
    CandidateProfile,
    DimensionScore,
    HardGateResult,
    JobRecord,
    ParsedJD,
    StrategicFit,
)
from app.services.evidence_loader import load_candidate_profile, load_evidence_library
from app.services import fit_engine

ROLE_FAMILY_SCORES: dict[str, int] = {
    "Technical Program Manager": 90,
    "Portfolio Manager": 90,
    "AI / Data Program Manager": 85,
    "Engineering Operations": 80,
    "Delivery / Agile": 65,
    "Product Manager": 50,
    "Architect": 40,
    "Software Engineering": 20,
    "Unknown / Other": 55,
}

SENIORITY_SCORES: dict[str, int] = {
    "Principal / Distinguished": 85,
    "Director+": 88,
    "Senior": 88,
    "Mid": 55,
    "Junior": 20,
}

EXCLUDED_DOMAINS = {"amazon", "cgi"}


def estimate_fit(
    job: JobRecord,
    jd: ParsedJD,
    gate: HardGateResult | None = None,
) -> StrategicFit:
    """
    Produce a heuristic StrategicFit from parsed JD signals and evidence library.
    All scores are deterministic Python computations.
    """
    candidate: CandidateProfile = load_candidate_profile()
    library = load_evidence_library()

    # ── Functional Fit (25%) ────────────────────────────────────────────────
    func_score = ROLE_FAMILY_SCORES.get(jd.role_family, 55)
    func_reason = (
        f"Role family '{jd.role_family}' aligns "
        f"{'well' if func_score >= 75 else 'partially'} with candidate target families."
    )
    # Penalize avoid list
    for avoid in candidate.avoid_or_selective:
        if any(a in (jd.role_family + " " + job.title).lower()
               for a in avoid.lower().split()):
            func_score = max(func_score - 25, 15)
            func_reason += f" Penalty: role overlaps with avoid list ({avoid})."
            break

    # ── Seniority Fit (15%) ─────────────────────────────────────────────────
    sen_score = SENIORITY_SCORES.get(jd.seniority or "Senior", 75)
    sen_reason = f"Seniority band '{jd.seniority or 'unspecified'}' vs candidate senior/lead/director level."

    # ── Domain Fit (10%) ────────────────────────────────────────────────────
    domain_keywords = [kw.text.lower() for kw in jd.keywords]
    candidate_caps = [c.lower() for c in candidate.core_capabilities]
    overlap = sum(1 for dk in domain_keywords if any(dk in cc or cc in dk
                                                       for cc in candidate_caps))
    dom_score = min(100, 40 + overlap * 8)
    dom_reason = f"{overlap} domain keyword overlap(s) with candidate core capabilities."

    # ── Evidence Strength (15%) ─────────────────────────────────────────────
    ev_keywords = set()
    for item in library:
        ev_keywords.update(k.lower() for k in item.capabilities + item.keywords)
    ev_overlap = sum(1 for dk in domain_keywords if any(dk in ek or ek in dk
                                                         for ek in ev_keywords))
    ev_score = min(100, 30 + ev_overlap * 10)
    ev_evidence_ids = [
        item.evidence_id for item in library
        if any(dk in " ".join(item.capabilities + item.keywords).lower()
               for dk in domain_keywords)
    ][:5]
    ev_reason = (
        f"{ev_overlap} requirement(s) backed by evidence library "
        f"items: {', '.join(ev_evidence_ids[:3]) or 'none'}."
    )

    # ── Location / Authorization (15%) ──────────────────────────────────────
    auth_clues = jd.location_auth_clues
    if gate and gate.authorization_status and "u.s." in gate.authorization_status.lower():
        loc_score = 20
        loc_reason = "U.S. work authorization required — candidate is Canada-based."
    elif auth_clues:
        loc_score = 45
        loc_reason = "Authorization clues detected — manual verification recommended."
    elif job.location and any(loc in (job.location or "").lower()
                               for loc in ["toronto", "canada", "remote", "ontario"]):
        loc_score = 95
        loc_reason = "Role in Toronto / Canada / Remote — strong location match."
    else:
        loc_score = 70
        loc_reason = "Location unclear or neutral — moderate score pending verification."

    # ── Competitive Positioning (10%) ────────────────────────────────────────
    # MBA + certifications + 20 years experience → strong positioning
    comp_score = 75
    comp_reason = (
        "Candidate has MBA (Rotman), SAFe LPM, SAFe Advanced Scrum Master, "
        "and 20+ years senior experience — above-average competitive positioning."
    )

    # ── Relationship Access (10%) ─────────────────────────────────────────────
    # Without authenticated data, default to moderate with manual uplift possible
    rel_score = 50
    rel_reason = (
        "No authenticated connection data available. "
        "Manual research or LinkedIn session can improve this score."
    )

    scores: dict[str, DimensionScore] = {
        "functional":    DimensionScore(score=func_score, rationale=func_reason,
                                        evidence_ids=[]),
        "seniority":     DimensionScore(score=sen_score, rationale=sen_reason),
        "domain":        DimensionScore(score=dom_score, rationale=dom_reason),
        "evidence":      DimensionScore(score=ev_score, rationale=ev_reason,
                                        evidence_ids=ev_evidence_ids),
        "location_auth": DimensionScore(score=loc_score, rationale=loc_reason),
        "competitive":   DimensionScore(score=comp_score, rationale=comp_reason),
        "relationship":  DimensionScore(score=rel_score, rationale=rel_reason),
    }

    barriers = (gate.barriers if gate else [])
    return fit_engine.calculate(scores, barriers=barriers)
