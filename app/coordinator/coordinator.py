"""
Coordinator Agent — orchestrates Scout → Resume → Submission pipeline.

Human gates:
  Gate 1: User approves/skips each discovered job  (status: discovered → approved/skipped)
  Gate 2: User approves tailored resume draft       (status: resume_ready → submission_approved)
  Gate 3: User confirms before final submit click   (inside Submission Agent)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.coordinator.queue import JobQueue, QueueEntry, _now
from app.coordinator.state import JobStatus

log = logging.getLogger("coordinator")

ROOT = Path(__file__).resolve().parent.parent.parent
SCOUT_STORE_PATH = ROOT / "data" / "scout" / "jobs.json"
TAILORED_DIR = ROOT / "data" / "tailored"


class CoordinatorAgent:
    """
    Coordinates the job application pipeline.

    Usage (from Streamlit UI):
        coordinator = CoordinatorAgent()
        coordinator.ingest_scout_results()          # Pull new Tier1/2 jobs from Scout store
        pending = coordinator.pending_approvals()    # Show in UI for user action
        coordinator.approve_job(job_id)             # Gate 1 ✓
        coordinator.run_tailoring(job_id)           # Trigger Resume Agent
        coordinator.approve_resume(job_id)          # Gate 2 ✓
        coordinator.submit_job(job_id)              # Trigger Submission Agent
    """

    def __init__(self, queue: Optional[JobQueue] = None):
        self.queue = queue or JobQueue.load()

    def save(self) -> None:
        self.queue.save()

    # ─────────────────────────────────────────────────────────────────────
    # Phase 1: Ingest from Scout
    # ─────────────────────────────────────────────────────────────────────

    def ingest_scout_results(
        self,
        min_tier: str = "tier_2",
        scout_path: Optional[Path] = None,
    ) -> int:
        """
        Pull open Tier1/Tier2 jobs from the Scout store and add any new ones
        to the coordinator queue as status=discovered.

        Returns: number of newly added jobs.
        """
        path = scout_path or SCOUT_STORE_PATH
        if not path.exists():
            log.warning("Scout store not found: %s", path)
            return 0

        store = json.loads(path.read_text(encoding="utf-8"))
        tier_priority = {"tier_1": 1, "tier_2": 2, "tier_3": 3}
        min_rank = tier_priority.get(min_tier, 2)

        added = 0
        for job in store.get("jobs", {}).values():
            if job.get("status") != "open":
                continue
            tier = job.get("tier", "")
            if tier_priority.get(tier, 99) > min_rank:
                continue
            if self.queue.upsert_from_scout(job):
                added += 1
                log.info("Queued: %s — %s (%s)", job.get("company"), job.get("title"), tier)

        if added:
            self.save()
        return added

    # ─────────────────────────────────────────────────────────────────────
    # Phase 2: User approval → Resume tailoring
    # ─────────────────────────────────────────────────────────────────────

    def approve_job(self, job_id: str, notes: str = "") -> bool:
        """Gate 1: User approves a discovered job for resume tailoring."""
        entry = self.queue.get(job_id)
        if not entry:
            return False
        entry.approve(notes)
        self.queue.update(entry)
        self.save()
        log.info("Approved for tailoring: %s", job_id)
        return True

    def skip_job(self, job_id: str, reason: str = "") -> bool:
        """Gate 1: User skips a discovered job."""
        entry = self.queue.get(job_id)
        if not entry:
            return False
        entry.skip(reason)
        self.queue.update(entry)
        self.save()
        return True

    def verify_contacts(self, job_id: str) -> "ContactVerificationResult | None":
        """
        Gate 1.5: Run the Contacts Agent for an approved job.
        Returns the ContactVerificationResult (or None on error).
        """
        entry = self.queue.get(job_id)
        if not entry:
            return None
        try:
            from app.agents.contacts_agent import ContactsAgent
            agent = ContactsAgent()
            result = agent.run(
                job_id=job_id,
                company=entry.company,
                title=entry.title,
                url=entry.url,
            )
            # Store contact count in queue for display
            entry._set("contacts_found", len(result.all_contacts()))
            entry._set("contacts_verified_at", _now())
            self.queue.update(entry)
            self.save()
            return result
        except Exception as exc:
            log.error("Contacts verification failed for %s: %s", job_id, exc)
            return None

    def load_contacts(self, job_id: str) -> "ContactVerificationResult | None":
        """Load a previously run contacts verification result."""
        try:
            from app.agents.contacts_agent import ContactsAgent
            return ContactsAgent().load(job_id)
        except Exception:
            return None

    def run_tailoring(self, job_id: str, feedback: str = "") -> Optional[str]:
        """
        Trigger the Resume Agent for an approved job.
        Returns the path to the generated .docx file, or None on error.

        The full JD is fetched from the Scout store on-demand.
        """
        entry = self.queue.get(job_id)
        if not entry:
            log.error("Job not found: %s", job_id)
            return None
        if entry.status not in (JobStatus.approved, JobStatus.rejected_resume):
            log.warning("Job %s is not in an approved state: %s", job_id, entry.status)
            return None

        # Fetch full JD from scout store
        jd_text = self._get_jd(job_id)
        if not jd_text:
            log.error("No JD text found for job %s", job_id)
            return None

        entry.start_tailoring()
        self.queue.update(entry)
        self.save()

        try:
            from app.orchestrator import load_master_resume
            from app.services import resume_tailor
            from app.services.evidence_loader import load_evidence_library
            from app.services.jd_parser import parse_jd
            from app.services.document_handler import save_docx

            master = load_master_resume(allow_fallback=True)
            evidence = load_evidence_library()
            parsed = parse_jd(jd_text, company=entry.company)

            tailored_text, meta = resume_tailor.tailor_resume(
                master_resume_text=master,
                job={"company": entry.company, "title": entry.title},
                parsed_jd=parsed,
                evidence=evidence,
                update_current_role=True,
                update_summary=True,
                update_competencies=True,
                update_tools=True,
            )

            # Save DOCX to data/tailored/{company}_{title}/
            safe_name = _safe_filename(entry.company, entry.title)
            out_dir = TAILORED_DIR / safe_name
            out_dir.mkdir(parents=True, exist_ok=True)
            docx_path = out_dir / "resume.docx"
            txt_path = out_dir / "resume.txt"

            # Save plain text version always
            txt_path.write_text(tailored_text, encoding="utf-8")

            # Save DOCX if document_handler supports it
            try:
                save_docx(tailored_text, str(docx_path))
                output_path = str(docx_path)
            except Exception:
                output_path = str(txt_path)

            entry.resume_ready(output_path)
            self.queue.update(entry)
            self.save()
            log.info("Tailored resume saved: %s", output_path)
            return output_path

        except Exception as exc:
            log.error("Tailoring failed for %s: %s", job_id, exc)
            entry._set("status", JobStatus.approved.value)  # Roll back
            entry._set("tailoring_error", str(exc))
            self.queue.update(entry)
            self.save()
            return None

    # ─────────────────────────────────────────────────────────────────────
    # Phase 3: Resume approval → Submission
    # ─────────────────────────────────────────────────────────────────────

    def approve_resume(self, job_id: str) -> bool:
        """Gate 2: User approves the tailored resume for submission."""
        entry = self.queue.get(job_id)
        if not entry or entry.status != JobStatus.resume_ready:
            return False
        entry.approve_submission()
        self.queue.update(entry)
        self.save()
        log.info("Resume approved for submission: %s", job_id)
        return True

    def reject_resume(self, job_id: str, feedback: str = "") -> bool:
        """Gate 2: User rejects the resume draft — send back for re-tailoring."""
        entry = self.queue.get(job_id)
        if not entry:
            return False
        entry.reject_resume(feedback)
        self.queue.update(entry)
        self.save()
        return True

    def submit_job(self, job_id: str, dry_run: bool = False) -> dict:
        """
        Gate 3: Trigger Submission Agent.
        Always requires human confirmation in the UI before calling this.

        Returns result dict with keys: success, confirmation, error
        """
        entry = self.queue.get(job_id)
        if not entry or entry.status != JobStatus.submission_approved:
            return {"success": False, "error": "Job not in submission_approved state"}

        resume_path = entry.tailored_resume_path
        if not resume_path or not Path(resume_path).exists():
            return {"success": False, "error": f"Resume file not found: {resume_path}"}

        entry.start_submitting()
        self.queue.update(entry)
        self.save()

        from app.agents.submission_agent import SubmissionAgent
        agent = SubmissionAgent()
        result = agent.submit(
            url=entry.url,
            resume_path=Path(resume_path),
            company=entry.company,
            title=entry.title,
            dry_run=dry_run,
        )

        if result["success"]:
            entry.mark_submitted(result.get("confirmation", ""))
        else:
            entry.mark_submission_failed(result.get("error", "Unknown error"))

        self.queue.update(entry)
        self.save()
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Queries for UI
    # ─────────────────────────────────────────────────────────────────────

    def pending_approvals(self) -> list[QueueEntry]:
        """Jobs waiting for Gate 1 (discovered)."""
        return self.queue.by_status(JobStatus.discovered)

    def resume_ready_for_review(self) -> list[QueueEntry]:
        """Jobs waiting for Gate 2 (resume_ready or rejected_resume)."""
        return self.queue.by_status(JobStatus.resume_ready, JobStatus.rejected_resume)

    def approved_for_submission(self) -> list[QueueEntry]:
        """Jobs cleared for Gate 3 (submission_approved)."""
        return self.queue.by_status(JobStatus.submission_approved)

    def in_progress(self) -> list[QueueEntry]:
        """Jobs being actively worked."""
        return self.queue.by_status(
            JobStatus.approved, JobStatus.tailoring,
            JobStatus.submitting,
        )

    def submitted(self) -> list[QueueEntry]:
        return self.queue.by_status(JobStatus.submitted, JobStatus.interview)

    def get_interview_record(self, job_id: str):
        """Load or create the InterviewRecord for a submitted job."""
        entry = self.queue.get(job_id)
        if not entry:
            return None
        from app.agents.interview_agent import InterviewAgent
        agent = InterviewAgent()
        return agent.get_or_create(
            job_id=job_id,
            company=entry.company,
            title=entry.title,
            url=entry.url,
        )

    def run_interview_assessment(self, job_id: str, force_refresh: bool = False) -> dict:
        """Run Claude assessment on the interview record for this job."""
        from app.agents.interview_agent import InterviewAgent
        agent = InterviewAgent()
        record = agent.load(job_id)
        if not record:
            return {"error": "No interview record found"}
        jd_text = self._get_jd(job_id)
        return agent.assess(record, jd_text=jd_text, force_refresh=force_refresh)

    def funnel_counts(self) -> dict[str, int]:
        """Summary counts for dashboard."""
        all_entries = self.queue.all()
        counts: dict[str, int] = {}
        for e in all_entries:
            counts[e.status.value] = counts.get(e.status.value, 0) + 1
        return counts

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def get_jd(self, job_id: str) -> str:
        """Fetch full JD for a job from Scout store or queue description."""
        jd = self._get_jd(job_id)
        if jd:
            return jd
        entry = self.queue.get(job_id)
        if entry:
            return getattr(entry, "description", "")
        return ""

    def _get_jd(self, job_id: str) -> str:
        """Fetch full JD from Scout store by job_id."""
        if not SCOUT_STORE_PATH.exists():
            return ""
        try:
            store = json.loads(SCOUT_STORE_PATH.read_text(encoding="utf-8"))
            job = store.get("jobs", {}).get(job_id, {})
            return job.get("description", "")
        except Exception:
            return ""


def _safe_filename(company: str, title: str) -> str:
    import re
    raw = f"{company}_{title}"
    safe = re.sub(r"[^\w\-]", "_", raw)
    return safe[:80]
