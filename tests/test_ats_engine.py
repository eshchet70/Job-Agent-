"""Tests for ATS engine — keyword actions, coverage calculations, evidence guardrails."""
import pytest

from app.models import EvidenceItem, KeywordAction, Requirement
from app.services.ats_engine import assess


RESUME = (
    "Technical program management portfolio governance roadmap planning "
    "stakeholder management risk management capacity planning Agile SAFe "
    "ServiceNow cloud modernization AI data initiatives cross-functional delivery "
    "vendor governance financial analysis TCO MBA"
)

EV = [
    EvidenceItem(
        id="BELL-TCO-01",
        employer="Bell Canada",
        role="Senior PM",
        claim="Led application TCO discovery",
        capabilities=["portfolio governance", "TCO", "financial management",
                       "stakeholder management", "ServiceNow"],
        safe_claims=["Led complex application TCO discovery"],
        evidence="Led application TCO discovery spanning 60+ stakeholder interviews.",
    ),
    EvidenceItem(
        id="AMZN-CATALOG-01",
        employer="Amazon",
        role="Senior PM",
        claim="Led cross-functional catalog programs",
        capabilities=["technical program management", "cross-functional delivery"],
        safe_claims=["Led cross-functional catalog and ontology programs"],
        evidence="Managed catalog programs spanning data scientists and 10+ engineers.",
    ),
]


def test_exact_match_with_evidence_is_keep():
    kws = [Requirement(text="technical program management", importance="critical", category="core")]
    result = assess(kws, RESUME, EV)
    assert result.matches[0].action == KeywordAction.keep
    assert result.matches[0].exact_match is True
    assert result.matches[0].evidence_ids != []


def test_supported_missing_keyword_is_add():
    kws = [Requirement(text="TCO", importance="critical", category="core")]
    result = assess(kws, "Portfolio leader program manager", EV)
    assert result.matches[0].action == KeywordAction.add
    assert result.matches[0].evidence_ids != []


def test_unsupported_missing_is_do_not_add():
    kws = [Requirement(text="blockchain development", importance="critical", category="technical")]
    result = assess(kws, RESUME, EV)
    assert result.matches[0].action == KeywordAction.do_not_add
    assert result.matches[0].evidence_ids == []


def test_add_action_always_has_evidence_ids():
    kws = [Requirement(text="stakeholder management", importance="critical", category="core")]
    result = assess(kws, "program manager portfolio", EV)
    for m in result.matches:
        if m.action == KeywordAction.add:
            assert m.evidence_ids, "ADD action must have supporting evidence IDs"


def test_critical_coverage_100_when_all_present():
    kws = [
        Requirement(text="technical program management", importance="critical", category="core"),
        Requirement(text="SAFe", importance="critical", category="technical"),
    ]
    result = assess(kws, RESUME, EV)
    assert result.critical_coverage == 100.0


def test_readiness_is_weighted_sum():
    kws = [Requirement(text="technical program management", importance="critical", category="core")]
    result = assess(kws, RESUME, EV)
    # Readiness should be ≤ 100 and > 0
    assert 0 < result.readiness <= 100


def test_no_keywords_returns_100_coverage():
    result = assess([], RESUME, EV)
    assert result.critical_coverage == 100.0
    assert result.important_coverage == 100.0


def test_evidence_coverage_zero_when_nothing_grounded():
    kws = [Requirement(text="quantum computing", importance="critical", category="technical")]
    result = assess(kws, RESUME, EV)
    assert result.evidence_coverage == 0.0


def test_resume_version_preserved():
    result = assess([], RESUME, EV, resume_version="v2.3")
    assert result.resume_version == "v2.3"
