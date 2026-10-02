"""
Unit tests for Coordinator Agent and JobQueue / QueueEntry.
"""
from pathlib import Path
import pytest
from app.coordinator.queue import JobQueue, QueueEntry
from app.coordinator.state import JobStatus


def test_queue_entry_properties():
    data = {
        "id": "job_123",
        "company": "Acme Inc",
        "title": "Senior TPM",
        "url": "https://example.com/jobs/123",
        "tier": "tier_1",
        "fit_score": 88.5,
        "ats_readiness": 75.0,
        "location": "Remote, USA",
        "posted_date": "2026-10-01",
        "description": "Great job opening",
        "matched_keywords": ["Python", "Cloud"],
        "missing_supported": [],
        "contacts_found": 2,
    }
    entry = QueueEntry(data)

    assert entry.id == "job_123"
    assert entry.company == "Acme Inc"
    assert entry.title == "Senior TPM"
    assert entry.url == "https://example.com/jobs/123"
    assert entry.tier == "tier_1"
    assert entry.fit_score == 88.5
    assert entry.ats_readiness == 75.0
    assert entry.location == "Remote, USA"
    assert entry.posted_date == "2026-10-01"
    assert entry.description == "Great job opening"
    assert entry.matched_keywords == ["Python", "Cloud"]
    assert entry.missing_supported == []
    assert entry.contacts_found == 2


def test_queue_entry_defaults():
    entry = QueueEntry({"id": "minimal"})

    assert entry.id == "minimal"
    assert entry.status == JobStatus.discovered
    assert entry.location == ""
    assert entry.matched_keywords == []
    assert entry.missing_supported == []
    assert entry.posted_date == ""
    assert entry.description == ""
    assert entry.contacts_found == 0
    assert entry.fit_score == 0.0
    assert entry.ats_readiness == 0.0


def test_queue_entry_getattr_fallback():
    entry = QueueEntry({"id": "custom", "custom_field": "val123"})
    assert entry.custom_field == "val123"

    with pytest.raises(AttributeError):
        _ = entry.non_existent_attribute


def test_job_queue_in_memory(tmp_path: Path):
    queue_file = tmp_path / "queue.json"
    queue = JobQueue(path=queue_file)

    entry = QueueEntry({"id": "job_abc", "company": "TestCo", "status": "discovered"})
    queue.add(entry)
    queue.save()

    loaded = JobQueue.load(path=queue_file)
    assert loaded.exists("job_abc")
    retrieved = loaded.get("job_abc")
    assert retrieved is not None
    assert retrieved.company == "TestCo"
    assert retrieved.location == ""


# ---------------------------------------------------------------------------
# Tailoring, pre-fill and scout sync (fake agents; no network, no browser)
# ---------------------------------------------------------------------------
import json  # noqa: E402

from app.agents.resume_agent import TailorOutcome  # noqa: E402
from app.coordinator import coordinator as coord_mod  # noqa: E402
from app.coordinator.coordinator import CoordinatorAgent  # noqa: E402

JOB_ID = "greenhouse:acme:1"


class FakeResumeAgent:
    model = "test-model"

    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def tailor(self, job, user_feedback=""):
        self.calls.append({"job": job, "user_feedback": user_feedback})
        return self.outcome


class FakeSubmissionAgent:
    def __init__(self, result):
        self.result, self.calls = result, []

    def prefill(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def coord(tmp_path, monkeypatch):
    scout = tmp_path / "jobs.json"
    scout.write_text(json.dumps({"jobs": {JOB_ID: {
        "id": JOB_ID, "status": "open", "tier": "tier_1", "company": "Acme", "title": "Senior TPM",
        "url": "https://boards.greenhouse.io/acme/jobs/1", "location": "Toronto, ON",
        "description": "Lead cross-functional programs.", "fit_score": 84, "ats_readiness": 70}}}))
    monkeypatch.setattr(coord_mod, "SCOUT_STORE_PATH", scout)
    monkeypatch.setattr(coord_mod, "TAILORED_DIR", tmp_path / "tailored")
    c = CoordinatorAgent(queue=JobQueue(path=tmp_path / "queue.json"))
    assert c.ingest_scout_results(scout_path=scout) == 1
    return c


GOOD = TailorOutcome(status="ready", markdown="# Elena\n\n## Professional Summary\nSummary.\n",
                     keywords_added=["roadmap"],
                     keywords_not_added=[{"keyword": "Kubernetes", "reason": "no evidence"}])


def test_tailoring_uses_resume_agent_and_records_fact_check(coord):
    coord.approve_job(JOB_ID)
    agent = FakeResumeAgent(GOOD)
    path = coord.run_tailoring(JOB_ID, agent=agent)
    entry = coord.queue.get(JOB_ID)
    assert path.endswith(".docx") and Path(path).exists()
    assert entry.status == JobStatus.resume_ready
    data = entry.as_dict()
    assert data["resume_check"] == "ready" and data["resume_model"] == "test-model"
    assert data["resume_keywords_not_added"] == ["Kubernetes"]
    assert Path(data["tailored_resume_text_path"]).read_text().startswith("# Elena")
    # The full job description from the scout store reaches the agent.
    assert agent.calls[0]["job"]["description"] == "Lead cross-functional programs."


def test_rejection_feedback_is_passed_to_the_next_draft(coord):
    coord.approve_job(JOB_ID)
    coord.run_tailoring(JOB_ID, agent=FakeResumeAgent(GOOD))
    coord.reject_resume(JOB_ID, "Lead with portfolio governance")
    agent = FakeResumeAgent(TailorOutcome(status="needs_review", markdown="# Elena\n",
                                          issues=["Number not found in sources: '42%'"]))
    coord.run_tailoring(JOB_ID, agent=agent)
    assert agent.calls[0]["user_feedback"] == "Lead with portfolio governance"
    data = coord.queue.get(JOB_ID).as_dict()
    assert data["status"] == "resume_ready" and data["resume_check"] == "needs_review"
    assert data["resume_issues"] == ["Number not found in sources: '42%'"]


def test_tailoring_without_api_key_explains_why(coord, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    coord.approve_job(JOB_ID)
    assert coord.run_tailoring(JOB_ID) is None
    entry = coord.queue.get(JOB_ID)
    assert entry.status == JobStatus.approved
    assert "ANTHROPIC_API_KEY" in entry.as_dict()["tailoring_error"]


def test_agent_error_rolls_back_to_previous_status(coord):
    coord.approve_job(JOB_ID)
    agent = FakeResumeAgent(TailorOutcome(status="error", error="401 invalid key"))
    assert coord.run_tailoring(JOB_ID, agent=agent) is None
    entry = coord.queue.get(JOB_ID)
    assert entry.status == JobStatus.approved and "401" in entry.as_dict()["tailoring_error"]


def test_prefill_never_marks_submitted_until_candidate_confirms(coord):
    coord.approve_job(JOB_ID)
    coord.run_tailoring(JOB_ID, agent=FakeResumeAgent(GOOD))
    coord.approve_resume(JOB_ID)
    sub = FakeSubmissionAgent({"success": True, "fields_filled": ["email", "resume_upload"]})
    result = coord.prefill_application(JOB_ID, agent=sub)
    assert result["success"] and sub.calls[0]["company"] == "Acme"
    assert coord.queue.get(JOB_ID).status == JobStatus.submission_approved
    assert coord.mark_applied(JOB_ID) is True
    assert coord.queue.get(JOB_ID).status == JobStatus.submitted


def test_mark_applied_requires_an_approved_resume(coord):
    assert coord.mark_applied(JOB_ID) is False


def test_ingest_auto_skips_jobs_the_scout_dropped(coord, tmp_path):
    scout = coord_mod.SCOUT_STORE_PATH
    store = json.loads(scout.read_text())
    store["jobs"][JOB_ID].update(status="filtered_out", filter_reason="US location")
    scout.write_text(json.dumps(store))
    coord.ingest_scout_results(scout_path=scout)
    entry = coord.queue.get(JOB_ID)
    assert entry.status == JobStatus.skipped and "US location" in entry.as_dict()["skip_reason"]
