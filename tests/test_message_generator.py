"""Tests for the message generator — guardrail enforcement."""
import pytest

from app.models import Confidence, JobRecord, PersonTarget, PersonType
from app.services.message_generator import generate_draft, message_context, GUARDRAILS


@pytest.fixture
def sample_person() -> PersonTarget:
    return PersonTarget(
        name="Jane Smith",
        current_title="Talent Partner",
        company="Telus",
        person_type=PersonType.recruiter,
        relationship_to_job="Recruiter for this role",
        relationship_status="inferred",
        confidence=Confidence.medium,
    )


@pytest.fixture
def hm_person() -> PersonTarget:
    return PersonTarget(
        name="John Doe",
        current_title="VP Technology",
        company="Telus",
        person_type=PersonType.hiring_manager,
        relationship_to_job="Likely hiring manager",
        relationship_status="inferred",
        confidence=Confidence.medium,
    )


def test_draft_generated_for_recruiter(sample_job, sample_person):
    rec = generate_draft(sample_job, sample_person)
    assert rec.draft is not None
    assert len(rec.draft) > 50
    assert "Elena" in rec.draft or "program" in rec.draft.lower()


def test_draft_pending_approval(sample_job, sample_person):
    from app.models import OutreachApproval
    rec = generate_draft(sample_job, sample_person)
    assert rec.approval_status == OutreachApproval.pending


def test_draft_has_evidence_ids(sample_job, sample_person):
    rec = generate_draft(sample_job, sample_person)
    assert len(rec.evidence_ids) > 0


def test_draft_uses_only_valid_evidence_ids(sample_job, sample_person):
    from app.services.evidence_loader import load_evidence_library
    library = load_evidence_library()
    valid_ids = {e.evidence_id for e in library}
    rec = generate_draft(sample_job, sample_person)
    for eid in rec.evidence_ids:
        assert eid in valid_ids, f"Evidence ID '{eid}' not in library"


def test_message_context_contains_guardrails(sample_job, sample_person):
    from app.services.evidence_loader import load_evidence_library
    ev = load_evidence_library()[:2]
    ctx = message_context(sample_job, sample_person, ev)
    assert "guardrails" in ctx
    assert len(ctx["guardrails"]) > 0


def test_message_context_excludes_draft_message(sample_job, sample_person):
    from app.services.evidence_loader import load_evidence_library
    ev = load_evidence_library()[:2]
    ctx = message_context(sample_job, sample_person, ev)
    # draft_message should be excluded from person context
    assert "draft_message" not in ctx["person"]


def test_hiring_manager_draft_different_from_recruiter(sample_job, sample_person, hm_person):
    recruiter_rec = generate_draft(sample_job, sample_person)
    hm_rec = generate_draft(sample_job, hm_person)
    # Drafts should be different in content / framing
    assert recruiter_rec.draft != hm_rec.draft


def test_draft_does_not_invent_email():
    job = JobRecord(company="Corp", title="Director", description="Lead programs.")
    person = PersonTarget(
        name="Mystery Person",
        current_title="Unknown",
        company="Corp",
        person_type=PersonType.warm_connector,
        relationship_to_job="Unknown connector",
        confidence=Confidence.low,
    )
    rec = generate_draft(job, person)
    assert "@" not in rec.draft or "example.com" not in rec.draft
