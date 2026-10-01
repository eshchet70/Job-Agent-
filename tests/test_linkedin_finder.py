"""
Unit tests for the LinkedIn discovery service (app/services/linkedin_finder.py).
"""
import pytest
from app.models import JobRecord, OpenStatus, PersonType, Confidence
from app.services.linkedin_finder import (
    build_search_strategies,
    parse_linkedin_input,
    get_candidate_affiliations,
)


@pytest.fixture
def sample_job():
    return JobRecord(
        id=42,
        company="Lightspeed Commerce",
        title="Staff Technical Program Manager - PDLC",
        description="We are looking for a Staff TPM to own and evolve our Product Development Lifecycle (PDLC).",
        location="Toronto, ON",
        status=OpenStatus.unknown,
    )


def test_build_search_strategies_structure(sample_job):
    strategies = build_search_strategies(sample_job)
    assert len(strategies) == 4
    archetypes = [s.archetype_id for s in strategies]
    assert "hiring_manager" in archetypes
    assert "recruiter" in archetypes
    assert "peer" in archetypes
    assert "warm_connector" in archetypes


def test_search_strategies_boolean_queries(sample_job):
    strategies = build_search_strategies(sample_job)
    hm = next(s for s in strategies if s.archetype_id == "hiring_manager")
    assert "Lightspeed Commerce" in hm.boolean_query
    assert "Director" in hm.boolean_query
    assert "Technical Program" in hm.boolean_query or "PDLC" in hm.boolean_query
    assert "https://www.linkedin.com/search/results/people/" in hm.linkedin_url
    assert "site%3Alinkedin.com%2Fin%2F" in hm.google_xray_url

    rec = next(s for s in strategies if s.archetype_id == "recruiter")
    assert "Technical Recruiter" in rec.boolean_query or "Talent Acquisition" in rec.boolean_query

    alumni = next(s for s in strategies if s.archetype_id == "warm_connector")
    assert "Rotman" in alumni.boolean_query or "Bell" in alumni.boolean_query or "Amazon" in alumni.boolean_query


def test_parse_linkedin_url():
    raw = "https://www.linkedin.com/in/alex-smith-tpm/"
    parsed = parse_linkedin_input(raw, default_company="Acme Corp")
    assert parsed["name"] == "Alex Smith Tpm"
    assert parsed["source_url"] == "https://www.linkedin.com/in/alex-smith-tpm"
    assert parsed["company"] == "Acme Corp"


def test_parse_linkedin_snippet():
    snippet = "Jane Doe · 2nd | Director of Product Operations at Lightspeed | Toronto, ON\nhttps://www.linkedin.com/in/janedoe"
    parsed = parse_linkedin_input(snippet, default_company="Lightspeed")
    assert "Jane Doe" in parsed["name"]
    assert "Director of Product Operations" in parsed["current_title"]
    assert parsed["person_type"] == PersonType.hiring_manager
    assert parsed["outreach_priority"] == 1
    assert parsed["source_url"] == "https://www.linkedin.com/in/janedoe"


def test_parse_recruiter_snippet():
    snippet = "Marcus Vance | Lead Technical Recruiter (Product & Engineering) at Stripe | linkedin.com/in/marcus-vance"
    parsed = parse_linkedin_input(snippet, default_company="Stripe")
    assert "Marcus Vance" in parsed["name"]
    assert parsed["person_type"] == PersonType.recruiter
    assert parsed["outreach_priority"] == 2


def test_get_discovered_contacts(sample_job):
    from app.services.linkedin_finder import get_discovered_contacts
    contacts = get_discovered_contacts(sample_job)
    assert len(contacts) >= 3
    assert any("Director" in (c["name"] + " " + c["current_title"]) for c in contacts)
    assert any(c["person_type"] == PersonType.hiring_manager for c in contacts)
    assert any(c["person_type"] == PersonType.recruiter for c in contacts)


def test_is_real_person_name():
    from app.services.linkedin_finder import is_real_person_name
    # Valid individual names
    assert is_real_person_name("Anita Nguyen") is True
    assert is_real_person_name("Derek Smockum") is True
    assert is_real_person_name("Vera Arkhipova") is True
    assert is_real_person_name("Duncan Wannamaker") is True
    assert is_real_person_name("Helen Lee") is True
    assert is_real_person_name("John Doe") is True

    # Companies, organizations, and corporate entities
    assert is_real_person_name("RWE") is False
    assert is_real_person_name("Rosenfelt & West Engineering") is False
    assert is_real_person_name("Rosenfelt & West") is False
    assert is_real_person_name("Lightspeed Commerce") is False
    assert is_real_person_name("Charles River Associates") is False
    assert is_real_person_name("Company Inc") is False
    assert is_real_person_name("Global Technologies Ltd") is False

    # Job titles and archetypes
    assert is_real_person_name("Head of AI Transformation") is False
    assert is_real_person_name("Lead Technical Recruiter") is False
    assert is_real_person_name("Talent Acquisition") is False
    assert is_real_person_name("Vice President Engineering") is False

    # Edge cases
    assert is_real_person_name("") is False
    assert is_real_person_name("SingleName") is False
    assert is_real_person_name("This Is A Very Long Name That Exceeds Word Limits") is False


def test_parse_linkedin_company_url_returns_error():
    company_url = "https://www.linkedin.com/company/rwe/people/?keywords=AI"
    parsed = parse_linkedin_input(company_url, default_company="RWE")
    assert "error" in parsed
    assert parsed.get("is_company_page") is True
    assert "company page" in parsed["error"].lower()


def test_get_discovered_contacts_unknown_company():
    from app.services.linkedin_finder import get_discovered_contacts
    rwe_job = JobRecord(
        id=3,
        company="RWE",
        title="Sr AI Transformation Manager",
        description="Lead AI transformation...",
        location="Toronto, ON",
        status=OpenStatus.unknown,
    )
    contacts = get_discovered_contacts(rwe_job)
    assert contacts == []


