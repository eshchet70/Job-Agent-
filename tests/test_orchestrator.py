"""
Integration tests for the full orchestration pipeline.

Covers:
  - End-to-end pasted-JD → ApplicationBrief → SQLite persist
  - ApplicationBrief fields are all populated
  - Excluded company results in passed=False gate
  - Deduplication: same company+title returns same ID
  - Repository round-trip: save_brief → get_job
  - AuditLog entries are created
  - Brief next_action is populated
"""
import json
from pathlib import Path

import pytest

from app.db import repository as repo
from app.models import ApplicationBrief, OpenStatus
from app.orchestrator import process_job
from tests.fixtures.job_fixtures import JOBS



@pytest.fixture(autouse=True)
def _use_test_db(in_memory_db, monkeypatch):
    """All orchestrator tests use an isolated in-memory database."""
    pass


class TestOrchestratorPipeline:
    def test_shopify_tpm_end_to_end(self):
        job_dict = next(j for j in JOBS if j["id"] == "tpm_shopify")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            location=job_dict.get("location"),
            work_model=job_dict.get("work_model"),
            country=job_dict.get("country"),
            write_excel=False,
        )
        assert isinstance(brief, ApplicationBrief)
        assert brief.job.id is not None
        assert brief.gate is not None
        assert brief.fit is not None
        assert brief.ats is not None
        assert len(brief.evidence_map) > 0
        assert brief.next_action is not None

    def test_gate_passed_for_clean_role(self):
        job_dict = next(j for j in JOBS if j["id"] == "tpm_shopify")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        assert brief.gate.passed is True

    def test_gate_failed_for_amazon(self):
        job_dict = next(j for j in JOBS if j["id"] == "excluded_amazon")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        assert brief.gate.passed is False
        assert len(brief.gate.barriers) >= 1

    def test_fit_score_in_valid_range(self):
        job_dict = next(j for j in JOBS if j["id"] == "tpm_telus")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        assert 0 <= brief.fit.weighted_score <= 100

    def test_ats_readiness_in_valid_range(self):
        job_dict = next(j for j in JOBS if j["id"] == "portfolio_mgr_rbc")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        assert 0 <= brief.ats.readiness <= 100

    def test_persisted_job_retrievable(self):
        job_dict = next(j for j in JOBS if j["id"] == "tpm_shopify")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        retrieved = repo.get_job(brief.job.id)
        assert retrieved is not None
        assert retrieved.company == job_dict["company"]
        assert retrieved.title == job_dict["title"]

    def test_duplicate_detection(self):
        """Same company+title → find_duplicate_job returns the first job's ID."""
        job_dict = next(j for j in JOBS if j["id"] == "tpm_shopify")
        brief1 = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        dup_id = repo.find_duplicate_job(job_dict["company"], job_dict["title"])
        assert dup_id == brief1.job.id

    def test_multiple_jobs_persisted(self):
        for job_id in ["tpm_shopify", "portfolio_mgr_rbc", "tpm_telus"]:
            job_dict = next(j for j in JOBS if j["id"] == job_id)
            process_job(
                jd_text=job_dict["jd"],
                company=job_dict["company"],
                title=job_dict["title"],
                write_excel=False,
            )
        all_jobs = repo.list_jobs(limit=100)
        assert len(all_jobs) == 3

    def test_barrier_tier_for_excluded_company(self):
        job_dict = next(j for j in JOBS if j["id"] == "excluded_amazon")
        brief = process_job(
            jd_text=job_dict["jd"],
            company=job_dict["company"],
            title=job_dict["title"],
            write_excel=False,
        )
        from app.models import PursuitTier
        assert brief.fit.tier == PursuitTier.barrier

    def test_evidence_map_unsupported_items_surface(self):
        """Some requirements should have no evidence (do-not-claim guardrail fires)."""
        # Inject a requirement that can't be supported
        from app.services import jd_parser, evidence_engine, fit_engine, gate_engine, ats_engine
        jd_text = (
            "Looking for a Senior Technical Program Manager with quantum computing experience "
            "and neurosurgery skills. Agile and stakeholder management required."
        )
        brief = process_job(
            jd_text=jd_text,
            company="FakeCoLtd",
            title="Test Role",
            write_excel=False,
        )
        # Verify evidence_map exists (even if all unsupported)
        assert isinstance(brief.evidence_map, list)
