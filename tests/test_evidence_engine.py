"""Tests for the evidence engine and evidence loader."""
import pytest

from app.models import EvidenceItem, Requirement
from app.services.evidence_engine import map_evidence
from app.services.evidence_loader import (
    get_evidence_by_id,
    is_safe_claim,
    is_unsafe_claim,
    load_evidence_library,
)


def test_evidence_library_loads():
    library = load_evidence_library()
    assert len(library) > 0


def test_evidence_library_all_have_ids():
    for item in load_evidence_library():
        assert item.evidence_id, f"Missing evidence_id for item: {item}"


def test_get_evidence_by_id_returns_correct():
    item = get_evidence_by_id("BELL-TCO-01")
    assert item is not None
    assert item.employer == "Bell Canada"


def test_get_evidence_by_id_missing_returns_none():
    assert get_evidence_by_id("NONEXISTENT-99") is None


def test_safe_claim_validation():
    assert is_safe_claim("Led complex application TCO discovery", "BELL-TCO-01")


def test_unsafe_claim_detected():
    assert is_unsafe_claim("Built ServiceNow platform", "BELL-TCO-01")


def test_map_evidence_returns_one_per_requirement():
    reqs = [
        Requirement(text="portfolio governance", importance="critical", category="core"),
        Requirement(text="quantum computing", importance="supporting", category="technical"),
    ]
    results = map_evidence(reqs)
    assert len(results) == 2


def test_supported_requirement_has_evidence():
    reqs = [Requirement(text="portfolio governance", importance="critical", category="core")]
    results = map_evidence(reqs)
    assert results[0].is_supported
    assert results[0].evidence_ids


def test_unsupported_requirement_flagged():
    reqs = [Requirement(text="quantum cryptography blockchain", importance="critical", category="technical")]
    results = map_evidence(reqs)
    assert not results[0].is_supported
    assert results[0].strength == "none"


def test_safe_wording_comes_from_safe_claims():
    reqs = [Requirement(text="ServiceNow", importance="critical", category="technical")]
    results = map_evidence(reqs)
    supported = [r for r in results if r.is_supported]
    if supported:
        assert supported[0].safe_wording is not None


def test_evidence_ids_are_all_from_library():
    library = load_evidence_library()
    valid_ids = {item.evidence_id for item in library}
    reqs = [Requirement(text="program management", importance="critical", category="core")]
    results = map_evidence(reqs)
    for r in results:
        for eid in r.evidence_ids:
            assert eid in valid_ids, f"Evidence ID '{eid}' not in library"
