"""
ATS Analysis engine.
Weights per FINAL_BUILD_SPEC.md:
  Critical keyword coverage 35%
  Important keyword coverage 20%
  Evidence coverage 25%
  Placement/prominence 10%
  Role/title/qualification alignment 10%

Keyword actions:
  KEEP     — already in resume and evidence-supported
  ADD      — absent from resume but evidence-grounded (must have evidence_id)
  STRENGTHEN — present but could be stronger
  DO_NOT_ADD — absent AND no supporting evidence
"""
from __future__ import annotations

from rapidfuzz import fuzz

from app.config import settings
from app.models import (
    ATSAssessment,
    EvidenceItem,
    KeywordAction,
    KeywordMatch,
    Requirement,
)

FUZZY_THRESHOLD = settings.ats_fuzzy_threshold   # default 82


def assess(
    keywords: list[Requirement],
    resume_text: str,
    evidence: list[EvidenceItem],
    resume_version: str | None = None,
    role_title: str = "",
) -> ATSAssessment:
    """
    Perform ATS keyword analysis against resume text and evidence library.

    Contract:
      - ADD requires at least one evidence_id (supported claim).
      - A keyword is DO_NOT_ADD when absent AND unsupported.
      - Semantic/fuzzy matching is applied only when exact match fails.
      - All scoring is deterministic Python; no LLM prose is trusted.
    """
    rt = resume_text.lower()
    # Build evidence corpus for fast substring lookup
    ev_corpus = " ".join(
        f"{e.claim} {' '.join(e.keywords + e.technologies + e.capabilities)}"
        for e in evidence
    ).lower()

    matches: list[KeywordMatch] = []

    for kw in keywords:
        kw_lower = kw.text.lower()

        # ── Exact match in resume ──────────────────────────────────────────
        exact = kw_lower in rt

        # ── Fuzzy / semantic match in resume ──────────────────────────────
        semantic = False
        if not exact:
            # Token set ratio handles word order variations well
            score = fuzz.token_set_ratio(kw_lower, rt)
            if score >= FUZZY_THRESHOLD:
                semantic = True

        # ── Evidence support ──────────────────────────────────────────────
        ev_ids = [
            e.evidence_id for e in evidence
            if kw_lower in (
                f"{e.claim} {' '.join(e.keywords + e.technologies + e.capabilities)}"
            ).lower()
            or fuzz.token_set_ratio(kw_lower,
               f"{e.claim} {' '.join(e.keywords + e.technologies + e.capabilities)}") >= FUZZY_THRESHOLD
        ]

        # ── Action assignment ──────────────────────────────────────────────
        # KEEP: keyword in resume AND evidence-supported
        # ADD: NOT in resume BUT evidence exists (only if ev_ids is non-empty)
        # STRENGTHEN: in resume but could be strengthened (rough heuristic: count ≤ 1)
        # DO_NOT_ADD: not in resume, no evidence
        if exact and ev_ids:
            action = KeywordAction.keep
            rationale = "Keyword present in resume with evidence support."
        elif exact and not ev_ids:
            # In resume but no grounding; suggest strengthening with evidence
            action = KeywordAction.strengthen
            rationale = "Keyword present but lacks direct evidence citation; strengthen with STAR example."
        elif not exact and not semantic and ev_ids:
            action = KeywordAction.add
            rationale = f"Keyword absent from resume but supported by evidence ({', '.join(ev_ids[:2])})."
        elif (exact or semantic) and not ev_ids:
            action = KeywordAction.strengthen
            rationale = "Keyword present/near-match but unsupported by evidence library."
        elif semantic and ev_ids:
            action = KeywordAction.add
            rationale = (
                f"Fuzzy match found (threshold {FUZZY_THRESHOLD}) with evidence support "
                f"({', '.join(ev_ids[:2])}); consider adding explicit terminology."
            )
        else:
            # Not in resume, not supported — DO NOT fabricate
            action = KeywordAction.do_not_add
            rationale = "Keyword absent and not supported by any evidence item; do not add."

        matches.append(KeywordMatch(
            keyword=kw.text,
            importance=kw.importance,
            category=kw.category,
            exact_match=exact,
            semantic_match=semantic,
            evidence_ids=ev_ids,
            action=action,
            rationale=rationale,
        ))

    # ── Coverage calculations ──────────────────────────────────────────────

    def _coverage(level: str) -> float:
        items = [m for m in matches if m.importance == level]
        if not items:
            return 100.0
        matched = sum(1 for m in items if m.exact_match or m.semantic_match)
        return round(100 * matched / len(items), 1)

    critical_cov = _coverage("critical")
    important_cov = _coverage("important")

    eligible = [m for m in matches if m.importance in ("critical", "important")]
    evidence_cov = (
        100.0 if not eligible
        else round(100 * sum(1 for m in eligible if m.evidence_ids) / len(eligible), 1)
    )

    # Placement score: heuristic — fraction of critical keywords in first 25% of resume
    placement = _placement_score(matches, resume_text)

    # Role/title alignment: check if the role_title tokens appear in resume
    role_align = _role_alignment(role_title, resume_text)

    # Weighted ATS readiness
    readiness = round(
        0.35 * critical_cov
        + 0.20 * important_cov
        + 0.25 * evidence_cov
        + 0.10 * placement
        + 0.10 * role_align,
        1,
    )

    return ATSAssessment(
        readiness=readiness,
        critical_coverage=critical_cov,
        important_coverage=important_cov,
        evidence_coverage=evidence_cov,
        placement_score=placement,
        role_alignment_score=role_align,
        matches=matches,
        resume_version=resume_version,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _placement_score(matches: list[KeywordMatch], resume_text: str) -> float:
    """Estimate how prominently critical keywords appear (early in resume = better)."""
    if not resume_text:
        return 50.0
    cutoff = len(resume_text) // 4
    first_quarter = resume_text[:cutoff].lower()
    critical = [m for m in matches if m.importance == "critical"]
    if not critical:
        return 100.0
    found_early = sum(1 for m in critical if m.keyword.lower() in first_quarter)
    return round(100 * found_early / len(critical), 1)


def _role_alignment(role_title: str, resume_text: str) -> float:
    """Check how many words from the role title appear in the resume."""
    if not role_title or not resume_text:
        return 50.0
    tokens = [t.lower() for t in role_title.split() if len(t) > 3]
    if not tokens:
        return 50.0
    rt_lower = resume_text.lower()
    found = sum(1 for t in tokens if t in rt_lower)
    return round(100 * found / len(tokens), 1)
