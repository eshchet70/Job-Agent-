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


def test_job_queue_find_entry(tmp_path: Path):
    queue_file = tmp_path / "queue.json"
    queue = JobQueue(path=queue_file)

    entry = QueueEntry({
        "id": "job_1",
        "company": "Amazon",
        "title": "Principal Technical Program Manager",
        "url": "https://amazon.jobs/en/jobs/123/",
    })
    queue.add(entry)

    # Find by ID
    assert queue.find_entry(job_id="job_1") is not None
    # Find by exact URL (with or without trailing slash)
    assert queue.find_entry(url="https://amazon.jobs/en/jobs/123") is not None
    # Find by Company and Title (case-insensitive)
    found = queue.find_entry(company="amazon", title="principal technical program manager")
    assert found is not None
    assert found.id == "job_1"

    # Not found
    assert queue.find_entry(company="Google", title="Engineer") is None


def test_detect_ats():
    from app.agents.submission_agent import detect_ats

    # Greenhouse URLs & embedded query params
    assert detect_ats("https://instacart.careers/job/?gh_jid=8249753") == "greenhouse"
    assert detect_ats("https://boards.greenhouse.io/instacart/jobs/8249753") == "greenhouse"
    assert detect_ats("https://grnh.se/abcde123") == "greenhouse"
    assert detect_ats("https://somecompany.com/apply?gh_src=custom") == "greenhouse"
    assert detect_ats("", job_id="greenhouse:instacart:8249753") == "greenhouse"

    # Ashby URLs & job_id
    assert detect_ats("https://jobs.ashbyhq.com/cohere/123") == "ashby"
    assert detect_ats("", job_id="ashby:cohere:123") == "ashby"

    # Lever URLs & job_id
    assert detect_ats("https://jobs.lever.co/netflix/123") == "lever"
    assert detect_ats("", job_id="lever:netflix:123") == "lever"

    # Workday URLs
    assert detect_ats("https://company.myworkdayjobs.com/careers/job/123") == "workday"
    assert detect_ats("", job_id="workday:company:123") == "workday"

    # Unknown
    assert detect_ats("https://customcompany.com/careers") == "unknown"


def test_approved_for_submission_includes_failed(tmp_path: Path):
    from app.coordinator.coordinator import CoordinatorAgent
    queue_file = tmp_path / "queue.json"
    queue = JobQueue(path=queue_file)

    approved_entry = QueueEntry({"id": "j1", "company": "Co1", "status": JobStatus.submission_approved.value})
    failed_entry = QueueEntry({"id": "j2", "company": "Co2", "status": JobStatus.submission_failed.value})
    discovered_entry = QueueEntry({"id": "j3", "company": "Co3", "status": JobStatus.discovered.value})

    queue.add(approved_entry)
    queue.add(failed_entry)
    queue.add(discovered_entry)

    coord = CoordinatorAgent(queue=queue)
    ready = coord.approved_for_submission()
    ready_ids = {e.id for e in ready}

    assert "j1" in ready_ids
    assert "j2" in ready_ids
    assert "j3" not in ready_ids

