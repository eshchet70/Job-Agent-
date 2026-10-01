"""
UI integration tests for Streamlit People & Outreach and in-app emailing.
Uses Streamlit AppTest framework.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app" / "ui" / "streamlit_app.py")


def test_people_outreach_screen_render():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    assert not at.exception

    # Switch to People & Outreach screen
    radio = at.sidebar.radio[0]
    radio.set_value("👥 People & Outreach")
    at.run(timeout=30)

    assert not at.exception
    metric_labels = [m.label for m in at.metric]
    assert "Total Contacts" in metric_labels
    assert "📨 Sent via Email" in metric_labels
    assert "✅ Approved" in metric_labels


def test_sidebar_smtp_settings_render():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    assert not at.exception

    # Check that SMTP provider selectbox exists
    provider_selects = [s for s in at.selectbox if "provider" in (s.key or "")]
    assert len(provider_selects) > 0


def test_simulated_email_send_via_button():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    radio = at.sidebar.radio[0]
    radio.set_value("👥 People & Outreach")
    at.run(timeout=30)

    # Ensure a job with contacts is selected if needed
    from app.db import repository as repo
    jobs = repo.list_jobs(limit=50)
    job_with_people = next((j for j in jobs if repo.get_people_for_job(j.id)), None)
    if job_with_people and at.selectbox:
        target_opt = next((opt for opt in at.selectbox[0].options if f"ID:{job_with_people.id}" in opt), None)
        if target_opt and at.selectbox[0].value != target_opt:
            at.selectbox[0].set_value(target_opt)
            at.run(timeout=30)

    # Find a simulated send button
    sim_buttons = [b for b in at.button if "btn_sim_send_" in (b.key or "")]
    assert len(sim_buttons) > 0

    # If the button is disabled because not approved, click approve first
    if sim_buttons[0].disabled:
        appr_btns = [b for b in at.button if "appr_" in (b.key or "") and not b.disabled]
        if appr_btns:
            appr_btns[0].click()
            at.run(timeout=30)
            sim_buttons = [b for b in at.button if "btn_sim_send_" in (b.key or "")]

    # Click the first simulated send button
    sim_buttons[0].click()
    at.run(timeout=30)

    assert not at.exception
    # Check that success message or sent metric is updated
    metric_labels = [m.label for m in at.metric]
    assert "📨 Sent via Email" in metric_labels


def test_non_approved_people_have_email_dispatch_disabled():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    radio = at.sidebar.radio[0]
    radio.set_value("👥 People & Outreach")
    at.run(timeout=30)

    # For any pending outreach record, send buttons must be disabled
    from app.db.database import get_session, OutreachDB
    s = get_session()
    pending_records = s.query(OutreachDB).filter(OutreachDB.approval_status == "pending").all()
    s.close()

    for rec in pending_records:
        send_btn = next((b for b in at.button if b.key == f"btn_send_now_{rec.id}"), None)
        if send_btn:
            assert send_btn.disabled is True, f"Send button for pending outreach {rec.id} was not disabled!"

        sim_btn = next((b for b in at.button if b.key == f"btn_sim_send_{rec.id}"), None)
        if sim_btn:
            assert sim_btn.disabled is True, f"Simulated send button for pending outreach {rec.id} was not disabled!"


def test_repository_record_email_sent_rejects_non_approved():
    from app.db import repository as repo
    from app.db.database import get_session, OutreachDB
    s = get_session()
    pending = s.query(OutreachDB).filter(OutreachDB.approval_status == "pending").first()
    s.close()

    if pending:
        with pytest.raises(PermissionError) as exc_info:
            repo.record_email_sent(pending.id, "test@example.com", "Subject")
        assert "Only approved outreach messages can be sent" in str(exc_info.value)


def test_application_status_update_and_retrieval():
    from datetime import datetime
    from app.db import repository as repo

    # Test update and retrieval on existing job 4
    app_id = repo.update_application_status(
        job_id=4,
        status="applied",
        applied_at=datetime(2026, 9, 23, 10, 0, 0),
        channel="company_site",
        status_source="linkedin",
        notes="Applied 1 week ago via company site",
        next_action="Follow up with hiring team",
    )
    assert app_id is not None

    app_rec = repo.get_application_for_job(4)
    assert app_rec is not None
    assert app_rec.status == "applied"
    assert app_rec.channel == "company_site"
    assert app_rec.status_source == "linkedin"
    assert app_rec.applied_at == datetime(2026, 9, 23, 10, 0, 0)
    assert "Applied 1 week ago" in app_rec.notes


def test_delete_person():
    from datetime import datetime, timezone
    from app.db import repository as repo
    from app.models import PersonTarget, PersonType, Confidence

    person = PersonTarget(
        name="Temporary Contact",
        current_title="Sourcer",
        company="Temporary Inc",
        person_type=PersonType.recruiter,
        relationship_to_job="Temporary recruiter",
        confidence=Confidence.medium,
        checked_at=datetime.now(timezone.utc),
    )
    pid = repo.save_person(4, person)
    assert pid is not None

    # Verify person is in people list
    people = repo.get_people_for_job(4)
    assert any(p.id == pid for p in people)

    # Delete person
    deleted = repo.delete_person(pid)
    assert deleted is True

    # Verify person is removed
    people_after = repo.get_people_for_job(4)
    assert not any(p.id == pid for p in people_after)

    # Deleting non-existent person returns False
    assert repo.delete_person(999999) is False


def test_get_brief_for_job():
    from app.db import repository as repo
    brief = repo.get_brief_for_job(3)
    if brief:
        assert brief.job.company.strip() == "RWE"
        assert brief.fit is not None
        assert brief.fit.weighted_score > 0
        assert brief.gate is not None
        assert brief.ats is not None
        assert brief.ats.readiness > 0


def test_application_quick_mark_and_revert():
    from datetime import datetime
    from app.db import repository as repo

    # Set job 3 to applied
    repo.update_application_status(
        job_id=3,
        status="applied",
        applied_at=datetime.utcnow(),
        channel="linkedin",
        status_source="user_action",
        notes="Applied via launchpad",
    )
    app = repo.get_application_for_job(3)
    assert app.status == "applied"
    assert app.channel == "linkedin"

    # Revert to draft
    repo.update_application_status(
        job_id=3,
        status="draft",
        notes="Reverted to draft",
    )
    app_draft = repo.get_application_for_job(3)
    assert app_draft.status == "draft"


def test_format_relative_time():
    from datetime import datetime, timezone, timedelta
    from app.ui.streamlit_app import format_relative_time

    now = datetime.now(timezone.utc)
    assert format_relative_time(now) == "today"
    assert format_relative_time(now - timedelta(days=1)) == "yesterday"
    assert format_relative_time(now - timedelta(days=5)) == "5 days ago"
    assert format_relative_time(now - timedelta(days=7)) == "1 week ago"
    assert format_relative_time(now - timedelta(days=14)) == "2 weeks ago"
    assert format_relative_time(None) == ""


def test_tier_management():
    from app.db import repository as repo

    fit = repo.get_fit_for_job(3)
    assert fit is not None
    assert "tier" in fit
    assert "weighted_score" in fit

    ats = repo.get_ats_for_job(3)
    assert ats is not None
    assert "readiness" in ats

    # Update tier
    updated = repo.update_job_tier(3, "tier_2", 78.5)
    assert updated is True

    fit_updated = repo.get_fit_for_job(3)
    assert fit_updated["tier"] == "tier_2"
    assert fit_updated["weighted_score"] == 78.5

    # Revert back to original
    repo.update_job_tier(3, "tier_3", 61.8)
    assert repo.get_fit_for_job(3)["tier"] == "tier_3"


def test_tailored_resume_generation_and_ats_boost():
    from app.models import JobRecord, ParsedJD, Requirement
    from app.services import resume_tailor
    import app.orchestrator as orch

    master = orch.load_master_resume(allow_fallback=True)
    job = JobRecord(
        company="Bell Canada",
        title="Director, Enterprise Program Delivery",
        description="Lead enterprise programs, cloud modernization, vendor governance, capacity planning, Jira.",
    )
    parsed_jd = ParsedJD(
        keywords=[
            Requirement(text="cloud modernization", importance="critical", category="domain"),
            Requirement(text="vendor governance", importance="important", category="governance"),
            Requirement(text="capacity planning", importance="critical", category="planning"),
        ],
        must_haves=[],
        preferred=[],
        seniority="Director",
        role_family="TPM",
    )

    tailored_text, meta = resume_tailor.tailor_resume(
        master_resume_text=master,
        job=job,
        parsed_jd=parsed_jd,
        selected_keywords=["cloud modernization", "vendor governance", "capacity planning"],
    )

    assert "Bell Canada" in tailored_text
    assert len(meta["current_role_bullets_after"]) >= len(meta["current_role_bullets_before"])

    impact = resume_tailor.evaluate_tailoring_impact(
        original_resume_text=master,
        tailored_resume_text=tailored_text,
        parsed_jd=parsed_jd,
        role_title=job.title,
    )
    assert impact["tailored_readiness"] >= impact["original_readiness"]




