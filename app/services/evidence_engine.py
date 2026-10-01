"""
Evidence engine — maps job requirements to evidence library items.

Every recommended candidate claim MUST resolve to at least one Evidence ID.
Returns EvidenceMapping objects with strength and safe wording.
"""
from __future__ import annotations

from app.models import EvidenceItem, EvidenceMapping, Requirement


def map_requirements(
    requirements: list[Requirement],
    evidence: list[EvidenceItem],
) -> list[EvidenceMapping]:
    """
    For each requirement, find matching evidence items and assign strength.

    Matching uses keyword/capability overlap. Strength assignment:
      strong  — 2+ evidence items match
      medium  — 1 evidence item matches
      weak    — 0 items but keyword appears in some adjacent claim
      none    — no overlap
    """
    mappings: list[EvidenceMapping] = []
    for req in requirements:
        needle = req.text.lower()
        matching_ids: list[str] = []
        safe_wordings: list[str] = []

        for ev in evidence:
            haystack = (
                ev.claim
                + " "
                + " ".join(ev.keywords)
                + " "
                + " ".join(ev.technologies)
                + " "
                + " ".join(ev.capabilities)
                + " "
                + " ".join(ev.safe_claims)
            ).lower()
            if needle in haystack:
                matching_ids.append(ev.evidence_id)
                if ev.safe_claims:
                    safe_wordings.append(ev.safe_claims[0])

        n = len(matching_ids)
        if n >= 2:
            strength = "strong"
        elif n == 1:
            strength = "medium"
        else:
            strength = "none"

        safe_wording = safe_wordings[0] if safe_wordings else None
        is_supported = n > 0

        mappings.append(
            EvidenceMapping(
                requirement=req.text,
                evidence_ids=matching_ids,
                strength=strength,  # type: ignore[arg-type]
                safe_wording=safe_wording,
                is_supported=is_supported,
            )
        )

    return mappings


def unsupported_requirements(mappings: list[EvidenceMapping]) -> list[str]:
    """Return requirement texts that have no evidence support."""
    return [m.requirement for m in mappings if not m.is_supported]


def evidence_coverage_pct(mappings: list[EvidenceMapping]) -> float:
    """Percentage of requirements that have at least one evidence item."""
    if not mappings:
        return 100.0
    supported = sum(1 for m in mappings if m.is_supported)
    return round(100.0 * supported / len(mappings), 1)


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------

def map_evidence(
    requirements: "list",
    evidence: "list | None" = None,
) -> "list":
    """
    Legacy name for map_requirements().
    When called with one arg, auto-loads the evidence library.
    Prefer map_requirements(requirements, evidence).
    """
    if evidence is None:
        from app.services.evidence_loader import load_evidence_library
        evidence = load_evidence_library()
    return map_requirements(requirements, evidence)

