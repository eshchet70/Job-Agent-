"""
Coordinator job queue — persisted as data/coordinator/queue.json.

Each entry tracks one job through its lifecycle from discovery to submission.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.coordinator.state import JobStatus

ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE_PATH = ROOT / "data" / "coordinator" / "queue.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QueueEntry:
    """Single job in the coordinator queue."""

    def __init__(self, data: dict[str, Any]):
        self._d = data

    # ── Accessors ──────────────────────────────────────────────────────────
    @property
    def id(self) -> str:
        return self._d["id"]

    @property
    def status(self) -> JobStatus:
        return JobStatus(self._d.get("status", "discovered"))

    @property
    def company(self) -> str:
        return self._d.get("company", "")

    @property
    def title(self) -> str:
        return self._d.get("title", "")

    @property
    def url(self) -> str:
        return self._d.get("url", "")

    @property
    def tier(self) -> str:
        return self._d.get("tier", "")

    @property
    def fit_score(self) -> float:
        return float(self._d.get("fit_score", 0))

    @property
    def ats_readiness(self) -> float:
        return float(self._d.get("ats_readiness", 0))

    @property
    def location(self) -> str:
        return self._d.get("location", "")

    @property
    def matched_keywords(self) -> list[str]:
        return self._d.get("matched_keywords", [])

    @property
    def missing_supported(self) -> list[str]:
        return self._d.get("missing_supported", [])

    @property
    def posted_date(self) -> str:
        return self._d.get("posted_date", "")

    @property
    def description(self) -> str:
        return self._d.get("description", "")

    @property
    def contacts_found(self) -> int:
        return int(self._d.get("contacts_found", 0))

    @property
    def submission_confirmation(self) -> str:
        return self._d.get("submission_confirmation", "")

    @property
    def submission_error(self) -> str:
        return self._d.get("submission_error", "")

    @property
    def tailored_resume_path(self) -> Optional[str]:
        return self._d.get("tailored_resume_path")

    @property
    def notes(self) -> str:
        return self._d.get("notes", "")

    @property
    def added_at(self) -> str:
        return self._d.get("added_at", "")

    def as_dict(self) -> dict[str, Any]:
        return dict(self._d)

    def __getattr__(self, name: str) -> Any:
        if "_d" in self.__dict__ and name in self._d:
            return self._d[name]
        raise AttributeError(f"'QueueEntry' object has no attribute '{name}'")

    # ── Transitions ────────────────────────────────────────────────────────
    def _set(self, key: str, value: Any) -> None:
        self._d[key] = value

    def approve(self, notes: str = "") -> None:
        self._set("status", JobStatus.approved.value)
        self._set("approved_at", _now())
        if notes:
            self._set("notes", notes)

    def skip(self, reason: str = "") -> None:
        self._set("status", JobStatus.skipped.value)
        self._set("skipped_at", _now())
        if reason:
            self._set("skip_reason", reason)

    def start_tailoring(self) -> None:
        self._set("status", JobStatus.tailoring.value)
        self._set("tailoring_started_at", _now())

    def resume_ready(self, path: str) -> None:
        self._set("status", JobStatus.resume_ready.value)
        self._set("tailored_resume_path", path)
        self._set("resume_ready_at", _now())

    def reject_resume(self, feedback: str = "") -> None:
        self._set("status", JobStatus.rejected_resume.value)
        self._set("resume_rejected_at", _now())
        if feedback:
            self._set("resume_feedback", feedback)

    def approve_submission(self) -> None:
        self._set("status", JobStatus.submission_approved.value)
        self._set("submission_approved_at", _now())

    def start_submitting(self) -> None:
        self._set("status", JobStatus.submitting.value)
        self._set("submitting_started_at", _now())

    def mark_submitted(self, confirmation: str = "") -> None:
        self._set("status", JobStatus.submitted.value)
        self._set("submitted_at", _now())
        if confirmation:
            self._set("submission_confirmation", confirmation)

    def mark_submission_failed(self, error: str = "") -> None:
        self._set("status", JobStatus.submission_failed.value)
        self._set("submission_failed_at", _now())
        if error:
            self._set("submission_error", error)

    def mark_outcome(self, outcome: str, notes: str = "") -> None:
        """outcome: 'interview' | 'rejected' | 'no_response'"""
        self._set("status", outcome)
        self._set("outcome_at", _now())
        if notes:
            self._set("outcome_notes", notes)


class JobQueue:
    """Persistent coordinator queue stored as JSON."""

    def __init__(self, path: Path = QUEUE_PATH, entries: dict[str, dict] = None):
        self.path = path
        self._entries: dict[str, dict] = entries or {}

    @classmethod
    def load(cls, path: Path = QUEUE_PATH) -> "JobQueue":
        path = Path(path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(path=path, entries=data.get("entries", {}))
            except Exception:
                pass
        return cls(path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now(),
            "entries": self._entries,
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ── Query ──────────────────────────────────────────────────────────────
    def get(self, job_id: str) -> Optional[QueueEntry]:
        if job_id in self._entries:
            return QueueEntry(self._entries[job_id])
        return None

    def all(self) -> list[QueueEntry]:
        return [QueueEntry(d) for d in self._entries.values()]

    def by_status(self, *statuses: JobStatus) -> list[QueueEntry]:
        vals = {s.value for s in statuses}
        return [QueueEntry(d) for d in self._entries.values()
                if d.get("status") in vals]

    def pending_count(self) -> int:
        """Jobs that need user action right now."""
        from app.coordinator.state import PENDING_USER_ACTION
        vals = {s.value for s in PENDING_USER_ACTION}
        return sum(1 for d in self._entries.values() if d.get("status") in vals)

    def exists(self, job_id: str) -> bool:
        return job_id in self._entries

    # ── Mutation ───────────────────────────────────────────────────────────
    def add(self, entry: QueueEntry) -> None:
        self._entries[entry.id] = entry.as_dict()

    def update(self, entry: QueueEntry) -> None:
        self._entries[entry.id] = entry.as_dict()

    def upsert_from_scout(self, scout_job: dict) -> bool:
        """Add a scout job to the queue if not already present. Returns True if newly added."""
        job_id = scout_job["id"]
        if job_id in self._entries:
            return False
        entry = QueueEntry({
            "id": job_id,
            "status": JobStatus.discovered.value,
            "company": scout_job.get("company", ""),
            "title": scout_job.get("title", ""),
            "url": scout_job.get("url", ""),
            "tier": scout_job.get("tier", ""),
            "fit_score": scout_job.get("fit_score", 0),
            "ats_readiness": scout_job.get("ats_readiness", 0),
            "location": scout_job.get("location", ""),
            "posted_date": scout_job.get("posted_date", ""),
            "description": (scout_job.get("description") or "")[:500],  # preview only
            "matched_keywords": scout_job.get("matched_keywords", []),
            "missing_supported": scout_job.get("missing_supported", []),
            "added_at": _now(),
        })
        self._entries[job_id] = entry.as_dict()
        return True
