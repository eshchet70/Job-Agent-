"""
Strategic Fit engine — deterministic weighted scoring.

Weights are defined in FINAL_BUILD_SPEC.md:
  Functional Fit      25
  Seniority Fit       15
  Domain Fit          10
  Evidence Strength   15
  Location/Auth       15
  Competitive         10
  Relationship Access 10

Tiers: >=80 Tier 1 | 70-79 Tier 2 | 60-69 Tier 3 | <60 DNP
Hard gates override score → barrier tier until resolved.

Dimension scores are calculated heuristically from ParsedJD + CandidateProfile.
The caller may also supply pre-built DimensionScore objects for each dimension
(e.g., from an LLM-backed step) — the final weighted sum is always recalculated
in Python and never trusted from model prose.
"""
from __future__ import annotations

from typing import Optional

from app.models import (
    CandidateProfile,
    DimensionScore,
    EvidenceItem,
    EvidenceMapping,
    HardGateResult,
    ParsedJD,
    PursuitTier,
    StrategicFit,
)

WEIGHTS: dict[str, float] = {
    "functional": 0.25,
    "seniority": 0.15,
    "domain": 0.10,
    "evidence": 0.15,
    "location_auth": 0.15,
    "competitive": 0.10,
    "relationship": 0.10,
}


# ---------------------------------------------------------------------------
# Main calculation (accepts pre-built scores or derives them automatically)
# ---------------------------------------------------------------------------

def calculate(
    scores: dict[str, DimensionScore],
    barriers: Optional[list[str]] = None,
) -> StrategicFit:
    """
    Given per-dimension DimensionScore objects, compute weighted total and tier.

    Args:
        scores: Keyed by dimension name (see WEIGHTS). All 7 keys required.
        barriers: Hard gate barriers — if any, tier is forced to 'barrier'.
    """
    barriers = barriers or []
    missing = set(WEIGHTS) - set(scores)
    if missing:
        raise ValueError(f"Missing dimension scores: {missing}")

    weighted = sum(scores[k].score * w for k, w in WEIGHTS.items())

    if barriers:
        tier = PursuitTier.barrier
    elif weighted >= 80:
        tier = PursuitTier.tier1
    elif weighted >= 70:
        tier = PursuitTier.tier2
    elif weighted >= 60:
        tier = PursuitTier.tier3
    else:
        tier = PursuitTier.do_not_pursue

    return StrategicFit(
        **scores,
        weighted_score=round(weighted, 1),
        tier=tier,
        barriers=barriers,
    )


# ---------------------------------------------------------------------------
# Heuristic auto-scorer (no LLM required)
# ---------------------------------------------------------------------------

def auto_score(
    jd: ParsedJD,
    candidate: CandidateProfile,
    evidence: list[EvidenceItem],
    evidence_mappings: list[EvidenceMapping],
    gate: Optional[HardGateResult] = None,
) -> StrategicFit:
    """
    Automatically derive all dimension scores using deterministic heuristics.
    Suitable for the no-LLM MVP path.
    """
    cap_lower = {c.lower() for c in candidate.core_capabilities}
    jd_keywords_lower = {r.text.lower() for r in jd.keywords}
    jd_must_lower = {r.text.lower() for r in jd.must_haves}

    # --- Functional Fit ---
    overlap = cap_lower & jd_keywords_lower
    must_overlap = cap_lower & jd_must_lower
    func_score = min(100, int(
        40 * (len(must_overlap) / max(len(jd_must_lower), 1))
        + 60 * (len(overlap) / max(len(jd_keywords_lower), 1))
    ))
    func_ev = [e.evidence_id for e in evidence if any(
        kw in (e.claim + " " + " ".join(e.keywords + e.capabilities)).lower()
        for kw in jd_must_lower
    )][:3]

    functional = DimensionScore(
        score=max(func_score, 10),
        rationale=(
            f"{len(must_overlap)}/{len(jd_must_lower)} critical keywords matched; "
            f"{len(overlap)} total keyword overlaps."
        ),
        evidence_ids=func_ev,
    )

    # --- Seniority Fit ---
    target_families_lower = " ".join(candidate.target_role_families).lower()
    seniority_score = 70  # default baseline for senior PM roles
    jd_seniority = jd.seniority or ""
    if jd_seniority in ("senior", "lead/director"):
        seniority_score = 85
    elif jd_seniority == "principal":
        seniority_score = 75
    elif jd_seniority == "junior":
        seniority_score = 30  # mismatch
    elif any(s in jd.role_family.lower() for s in ["director", "vp"]):
        seniority_score = 70

    seniority = DimensionScore(
        score=seniority_score,
        rationale=f"JD seniority signals: {jd_seniority or 'not detected'}. "
                  f"Candidate targets senior/lead/principal TPM/portfolio roles.",
    )

    # --- Domain Fit ---
    domain_keywords = {
        "ai": 20, "machine learning": 15, "cloud": 10, "e-commerce": 10,
        "telecom": 10, "public sector": 5, "platform": 10, "data": 10,
        "portfolio": 15, "enterprise": 10, "transformation": 10,
    }
    domain_text = (jd.role_family + " " + job_description_sample(jd)).lower()
    domain_score = 50
    for kw, pts in domain_keywords.items():
        if kw in domain_text and kw in target_families_lower:
            domain_score = min(100, domain_score + pts)
    domain = DimensionScore(
        score=domain_score,
        rationale=f"Role family: {jd.role_family}. Candidate domain coverage evaluated.",
    )

    # --- Evidence Strength ---
    supported = sum(1 for m in evidence_mappings if m.is_supported)
    total = len(evidence_mappings) or 1
    strong_count = sum(1 for m in evidence_mappings if m.strength == "strong")
    ev_score = min(100, int(
        50 * (supported / total)
        + 50 * (strong_count / max(supported, 1))
    ))
    ev_ids = list({eid for m in evidence_mappings for eid in m.evidence_ids})[:5]
    evidence_dim = DimensionScore(
        score=max(ev_score, 10),
        rationale=f"{supported}/{total} requirements have evidence; {strong_count} strong.",
        evidence_ids=ev_ids,
    )

    # --- Location / Authorization ---
    auth_clues = jd.location_auth_clues
    loc_score = 85  # default: no barrier
    auth_status = "eligible"
    if gate and gate.barriers:
        for b in gate.barriers:
            if "work-authorization" in b.lower() or "location" in b.lower():
                loc_score = 10
                auth_status = "barrier"
                break
    if "canada_mentioned" in auth_clues or "remote_ok" in auth_clues:
        loc_score = min(100, loc_score + 10)

    location_auth = DimensionScore(
        score=loc_score,
        rationale=(
            f"Location/auth status: {auth_status}. "
            f"Clues: {', '.join(auth_clues) or 'none detected'}."
        ),
    )

    # --- Competitive Positioning ---
    # Heuristic: seniority alignment + evidence depth signal positioning
    comp_score = min(100, max(40, (func_score + seniority_score) // 2 - 5))
    competitive = DimensionScore(
        score=comp_score,
        rationale="Heuristic: functional + seniority alignment proxy for competitive position.",
    )

    # --- Relationship Access ---
    # No people data at parse time — set to 50 (neutral/unknown)
    relationship = DimensionScore(
        score=50,
        rationale="No people/connection data yet. Score will update after people research.",
    )

    barriers = gate.barriers if gate else []

    return calculate(
        scores={
            "functional": functional,
            "seniority": seniority,
            "domain": domain,
            "evidence": evidence_dim,
            "location_auth": location_auth,
            "competitive": competitive,
            "relationship": relationship,
        },
        barriers=barriers,
    )


def job_description_sample(jd: ParsedJD, chars: int = 500) -> str:
    """Extract a text sample from raw_extracted or return empty string."""
    return str(jd.raw_extracted.get("text_sample", ""))[:chars]
