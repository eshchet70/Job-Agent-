"""
Evidence & candidate profile loader.
Reads data/candidate_profile.json and data/evidence_library.json once and caches them.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import CandidateProfile, EvidenceItem


@lru_cache(maxsize=1)
def load_candidate_profile() -> CandidateProfile:
    path = Path(settings.candidate_profile_path)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return CandidateProfile.model_validate(data)


@lru_cache(maxsize=1)
def load_evidence_library() -> list[EvidenceItem]:
    path = Path(settings.evidence_library_path)
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return [EvidenceItem.model_validate(item) for item in raw]


def get_evidence_by_id(evidence_id: str) -> Optional[EvidenceItem]:
    for item in load_evidence_library():
        if item.evidence_id == evidence_id:
            return item
    return None


def get_evidence_by_capability(capability: str) -> list[EvidenceItem]:
    """Return all evidence items that include the given capability tag."""
    cap_lower = capability.lower()
    return [
        item for item in load_evidence_library()
        if any(cap_lower in c.lower() for c in item.capabilities + item.keywords)
    ]


def is_safe_claim(claim_text: str, evidence_id: str) -> bool:
    """Return True if claim_text matches a known safe claim for the evidence item."""
    item = get_evidence_by_id(evidence_id)
    if not item:
        return False
    claim_lower = claim_text.lower()
    return any(claim_lower in sc.lower() for sc in item.safe_claims)


def is_unsafe_claim(claim_text: str, evidence_id: str) -> bool:
    """Return True if claim_text matches a known unsafe claim for the evidence item."""
    item = get_evidence_by_id(evidence_id)
    if not item:
        return False
    claim_lower = claim_text.lower()
    return any(claim_lower in uc.lower() for uc in item.unsafe_claims)


def all_candidate_keywords() -> list[str]:
    """Return all capability keywords across the evidence library."""
    seen: set[str] = set()
    result = []
    for item in load_evidence_library():
        for kw in item.capabilities + item.keywords + item.technologies:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                result.append(kw)
    return result
