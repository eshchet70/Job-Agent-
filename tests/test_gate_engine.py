"""
Tests for the hard gates engine.

Covers:
  - Amazon/CGI company exclusion → passed=False
  - US work-auth / no-sponsorship barrier (with CA-only profile)
  - Profession mismatch (hands-on SWE description)
  - Mandatory clearance credential barrier
  - Clean Canadian TPM role passes all gates
  - HardGateResult fields are all populated
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import JobRecord, ParsedJD
from app.services.gate_engine import evaluate


def _candidate() -> dict:
    with open(Path(__file__).parent.parent / "data" / "candidate_profile.json") as f:
        return json.load(f)


# Stripped profile with NO US secondary geography — forces US auth barrier to fire
_CANADA_ONLY_PROFILE: dict = {
    "geography": {
        "primary": "Canada",
        "secondary": [],            # no US auth → barrier must fire
        "work_model_preference": "remote",
    }
}


def _jd(clues: list[str] | None = None, company_clues: list[str] | None = None) -> ParsedJD:
    return ParsedJD(
        role_family="Technical Program Management",
        location_auth_clues=clues or [],
        company_clues=company_clues or [],
    )


# ── Company exclusion ────────────────────────────────────────────────────────

def test_amazon_exclusion_is_barrier(amazon_job):
    result = evaluate(amazon_job, _jd(), _candidate())
    assert not result.passed
    assert any("amazon" in b.lower() for b in result.barriers)


def test_cgi_exclusion_is_barrier(cgi_job):
    result = evaluate(cgi_job, _jd(), _candidate())
    assert not result.passed
    assert any("cgi" in b.lower() for b in result.barriers)


def test_gate_result_has_company_exclusion_detail(amazon_job):
    result = evaluate(amazon_job, _jd(), _candidate())
    assert result.company_exclusion is not None


# ── Work-authorization barriers ──────────────────────────────────────────────

def test_us_auth_barrier(us_only_job):
    # Use CA-only profile so candidate has no US auth → barrier fires
    result = evaluate(
        us_only_job,
        _jd(["must be authorized to work in the united states"]),
        _CANADA_ONLY_PROFILE,
    )
    assert not result.passed
    assert any(
        "authorization" in b.lower() or "sponsorship" in b.lower()
        for b in result.barriers
    )


def test_no_sponsorship_text_triggers_barrier():
    job = JobRecord(
        company="Tech Corp",
        title="Director PM",
        description="No visa sponsorship is available for this role. Must work in USA.",
        location="San Francisco, CA",
    )
    # CA-only profile ensures the barrier isn't suppressed by US geography
    result = evaluate(job, _jd(["no visa sponsorship"]), _CANADA_ONLY_PROFILE)
    assert not result.passed


# ── Profession mismatch ──────────────────────────────────────────────────────

def test_hands_on_engineering_barrier():
    """A JD that says 'hands-on software engineer' should block the candidate."""
    swe_job = JobRecord(
        company="StartupX",
        title="Staff Software Engineer",
        description="You will be a hands-on software engineer writing production code daily in Python.",
        location="Toronto",
    )
    result = evaluate(swe_job, _jd(), _candidate())
    assert not result.passed
    assert any(
        "engineering" in b.lower() or "technical skills" in b.lower()
        for b in result.barriers
    )


# ── Mandatory credentials ────────────────────────────────────────────────────

def test_clearance_required_barrier():
    job = JobRecord(
        company="Defense Co",
        title="Program Manager",
        description="Security clearance required. Active secret clearance mandatory.",
        location="Ottawa",
    )
    result = evaluate(job, _jd(), _candidate())
    assert not result.passed
    assert any("clearance" in b.lower() for b in result.barriers)


# ── Clean pass ───────────────────────────────────────────────────────────────

def test_clean_canadian_tpm_passes(sample_job):
    result = evaluate(sample_job, _jd(), _candidate())
    assert result.passed
    assert result.barriers == []


# ── Field completeness ───────────────────────────────────────────────────────

def test_gate_result_fields_all_populated(sample_job):
    result = evaluate(sample_job, _jd(), _candidate())
    assert result.authorization_status is not None
    assert result.location_status is not None
    assert result.profession_match is not None
    assert result.mandatory_credential_status is not None
    assert isinstance(result.barriers, list)
