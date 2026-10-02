"""
Coordinator Agent — orchestrates Scout → Resume → Submission pipeline.

Human gates:
  Gate 1: User approves/skips each discovered job  (status: discovered → approved/skipped)
  Gate 2: User approves tailored resume draft       (status: resume_ready → submission_approved)
  Gate 3: Agent pre-fills the form; the user submits it herself and marks it applied
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
        coordinator.prefill_application(job_id)     # Open + pre-fill the form (never submits)
        coordinator.mark_applied(job_id)            # Gate 3 ✓ after the user submits it herself
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
        changed = False
        scout_jobs = store.get("jobs", {})

        # Jobs still waiting for a Gate 1 decision whose posting has since closed,
        # or been dropped by the scout's filters, should not stay in the review list.
        for entry in self.queue.by_status(JobStatus.discovered):
            scout_status = scout_jobs.get(entry.id, {}).get("status")
            if scout_status in ("closed", "expired", "filtered_out"):
                reason = scout_jobs[entry.id].get("filter_reason") or f"posting {scout_status}"
                entry.skip(f"Auto-skipped: {reason}")
                self.queue.update(entry)
                changed = True
                log.info("Auto-skipped %s (%s)", entry.id, reason)

        for job in scout_jobs.values():
            if job.get("status") != "open":
                continue
            tier = job.get("tier", "")
            if tier_priority.get(tier, 99) > min_rank:
                continue
            if self.queue.upsert_from_scout(job):
                added += 1
                log.info("Queued: %s — %s (%s)", job.get("company"), job.get("title"), tier)

        if added or changed:
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

    def run_tailoring(self, job_id: str, feedback: str = "", agent=None) -> Optional[str]:
        """
        Run the Claude resume agent for an approved (or resume-rejected) job.

        The agent rewrites the master resume for this posting using only facts
        from the master resume and the evidence library's safe claims, then
        fact-checks the draft. Returns the path of the .docx, or None on error
        (the reason is stored on the entry as `tailoring_error`).

        Args:
            feedback: the candidate's notes from rejecting an earlier draft. If
                      empty, feedback saved by reject_resume() is used.
            agent:    a ResumeAgent (tests inject one with a fake client).
        """
        import os

        entry = self.queue.get(job_id)
        if not entry:
            log.error("Job not found: %s", job_id)
            return None
        previous_status = entry.status
        if previous_status not in (JobStatus.approved, JobStatus.rejected_resume):
            log.warning("Job %s is not in an approved state: %s", job_id, previous_status)
            return None

        def fail(message: str) -> None:
            log.error("Tailoring failed for %s: %s", job_id, message)
            entry._set("status", previous_status.value)
            entry._set("tailoring_error", message)
            self.queue.update(entry)
            self.save()

        # The full JD lives in the Scout store (the queue keeps only a preview).
        jd_text = self._get_jd(job_id)
        if not jd_text:
            fail("No job description stored for this job. Run the Scout again, then retry.")
            return None
        if agent is None and not os.getenv("ANTHROPIC_API_KEY"):
            fail("ANTHROPIC_API_KEY is not set. Add it to the .env file in the project folder "
                 "and restart the app.")
            return None

        feedback = feedback or entry.as_dict().get("resume_feedback", "")
        entry.start_tailoring()
        self.queue.update(entry)
        self.save()

        try:
            from app.agents.resume_agent import ResumeAgent, safe_filename, write_outputs

            agent = agent or ResumeAgent()
            job = {"id": job_id, "company": entry.company, "title": entry.title,
                   "location": entry.location, "url": entry.url, "description": jd_text}
            outcome = agent.tailor(job, user_feedback=feedback)
            if outcome.status == "error":
                fail(outcome.error or "The resume agent returned an error.")
                return None

            out_dir = TAILORED_DIR / _safe_filename(entry.company, entry.title)
            paths = write_outputs(outcome, job, out_dir, safe_filename(entry.company, entry.title))

            entry.resume_ready(str(paths["docx"]))
            entry._set("tailored_resume_text_path", str(paths["md"]))
            entry._set("tailored_resume_notes_path", str(paths["notes"]))
            # "ready" = passed every fact check; "needs_review" = issues listed below.
            entry._set("resume_check", outcome.status)
            entry._set("resume_issues", outcome.issues[:10])
            entry._set("resume_keywords_added", outcome.keywords_added[:15])
            entry._set("resume_keywords_not_added",
                       [k.get("keyword", "") for k in outcome.keywords_not_added][:15])
            entry._set("resume_model", agent.model)
            entry._set("resume_feedback_applied", feedback)
            entry._set("tailoring_error", "")
            self.queue.update(entry)
            self.save()
            log.info("Tailored resume saved: %s (%s)", paths["docx"], outcome.status)
            return str(paths["docx"])

        except Exception as exc:
            fail(str(exc)[:300])
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

    def prefill_application(self, job_id: str, keep_open: bool = True, agent=None) -> dict:
        """
        Gate 3: open the application form in a browser and pre-fill it.

        Nothing is submitted. The candidate finishes the form and clicks Submit
        herself, then confirms with mark_applied(). The job stays in
        `submission_approved` until she does.

        Returns the Submission Agent's result dict (success, fields_filled,
        fields_skipped, screenshot, error).
        """
        entry = self.queue.get(job_id)
        if not entry or entry.status not in (JobStatus.submission_approved,
                                             JobStatus.submission_failed):
            return {"success": False, "error": "Job is not approved for submission"}

        resume_path = entry.tailored_resume_path
        if not resume_path or not Path(resume_path).exists():
            return {"success": False, "error": f"Resume file not found: {resume_path}"}

        if agent is None:
            from app.agents.submission_agent import SubmissionAgent
            agent = SubmissionAgent()
        result = agent.prefill(
            url=entry.url,
            resume_path=Path(resume_path),
            company=entry.company,
            title=entry.title,
            keep_open=keep_open,
        )

        entry._set("status", JobStatus.submission_approved.value)
        entry._set("prefilled_at", _now())
        entry._set("prefill_fields", result.get("fields_filled", []))
        entry._set("submission_error", "" if result.get("success") else result.get("error", ""))
        self.queue.update(entry)
        self.save()
        return result

    def mark_applied(self, job_id: str, note: str = "") -> bool:
        """The candidate confirms she submitted the application herself."""
        entry = self.queue.get(job_id)
        if not entry or entry.status not in (JobStatus.submission_approved,
                                             JobStatus.submission_failed):
            return False
        entry.mark_submitted(note or "Submitted by candidate")
        entry._set("submission_error", "")
        self.queue.update(entry)
        self.save()
        log.info("Marked as applied: %s", job_id)
        return True

    def submit_job(self, job_id: str, dry_run: bool = True) -> dict:
        """Deprecated name kept for older callers. Pre-fills only; never submits."""
        return self.prefill_application(job_id, keep_open=not dry_run)

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
