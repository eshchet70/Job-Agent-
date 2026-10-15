"""Application service for qualifying a job and optionally saving its results."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from app.models import (
    ApplicationBrief,
    JobRecord,
    OpenStatus,
    OutreachRecord,
    PersonTarget,
)
from app.services import (
    ats_engine,
    evidence_engine,
    fit_estimator,
    gate_engine,
    jd_parser,
    message_generator,
    people_research,
)
from app.services.evidence_loader import load_evidence_library
from app.services.resume_store import load_master_resume


class JobRepository(Protocol):
    def find_duplicate_job(self, company: str, title: str) -> Optional[int]: ...
    def get_brief_for_job(self, job_id: int) -> Optional[ApplicationBrief]: ...
    def get_job(self, job_id: int) -> Optional[JobRecord]: ...
    def save_brief(self, brief: ApplicationBrief) -> int: ...
    def save_person(self, job_id: int, person: PersonTarget) -> int: ...
    def save_outreach(self, record: OutreachRecord) -> int: ...


class TrackerWriter(Protocol):
    def write_brief_to_tracker(self, brief: ApplicationBrief) -> None: ...


def _default_resume_loader() -> str:
    return load_master_resume(allow_fallback=True)


class JobAnalysisService:
    """Run job analysis independently, with persistence supplied through ports."""

    def __init__(
        self,
        repository: Optional[JobRepository] = None,
        tracker: Optional[TrackerWriter] = None,
        resume_loader=_default_resume_loader,
        evidence_loader=load_evidence_library,
    ) -> None:
        self.repository = repository
        self.tracker = tracker
        self.resume_loader = resume_loader
        self.evidence_loader = evidence_loader

    def analyze(
        self,
        company: str,
        title: str,
        description: str,
        location: Optional[str] = None,
        country: Optional[str] = None,
        work_model: Optional[str] = None,
        official_url: Optional[str] = None,
        source_type: str = "manual",
        people_list: Optional[list[dict]] = None,
    ) -> ApplicationBrief:
        """Build an analysis brief without database or tracker side effects."""
        job = JobRecord(
            company=company,
            title=title,
            description=description,
            location=location,
            country=country,
            work_model=work_model,
            official_url=official_url,
            source_type=source_type,
            status=OpenStatus.unknown,
            verified_at=datetime.now(timezone.utc),
        )
        parsed_jd = jd_parser.parse_jd(description, company=company)
        job.role_family = parsed_jd.role_family
        job.seniority = parsed_jd.seniority

        gate = gate_engine.evaluate_gates(job, parsed_jd)
        fit = fit_estimator.estimate_fit(job, parsed_jd, gate)
        evidence_library = self.evidence_loader()
        ats = ats_engine.assess(
            keywords=parsed_jd.keywords + parsed_jd.must_haves + parsed_jd.preferred,
            resume_text=self.resume_loader(),
            evidence=evidence_library,
            role_title=title,
        )
        evidence_map = evidence_engine.map_evidence(
            requirements=parsed_jd.must_haves + parsed_jd.preferred,
            evidence=evidence_library,
        )

        people: list[PersonTarget] = []
        outreach: list[OutreachRecord] = []
        if people_list:
            people = people_research.normalize_people(people_list)
            outreach = [message_generator.generate_draft(job, person) for person in people]

        return ApplicationBrief(
            job=job,
            parsed_jd=parsed_jd,
            gate=gate,
            fit=fit,
            ats=ats,
            evidence_map=evidence_map,
            people=people,
            outreach=outreach,
            positioning=self._build_positioning(fit, gate, ats),
            next_action=self._determine_next_action(fit, gate),
            created_at=datetime.now(timezone.utc),
        )

    def execute(
        self,
        company: str,
        title: str,
        description: str,
        location: Optional[str] = None,
        country: Optional[str] = None,
        work_model: Optional[str] = None,
        official_url: Optional[str] = None,
        source_type: str = "manual",
        people_list: Optional[list[dict]] = None,
        write_to_excel: bool = False,
    ) -> ApplicationBrief:
        """Analyze, persist, and optionally sync a job through injected adapters."""
        if self.repository is None:
            raise RuntimeError("A repository is required to execute and persist job analysis.")

        existing_id = self.repository.find_duplicate_job(company, title)
        if existing_id:
            existing_brief = self.repository.get_brief_for_job(existing_id)
            if existing_brief:
                return existing_brief
            existing_job = self.repository.get_job(existing_id)
            if existing_job:
                return ApplicationBrief(
                    job=existing_job,
                    next_action="Duplicate detected — see existing record.",
                )

        brief = self.analyze(
            company=company,
            title=title,
            description=description,
            location=location,
            country=country,
            work_model=work_model,
            official_url=official_url,
            source_type=source_type,
            people_list=people_list,
        )
        job_id = self.repository.save_brief(brief)
        brief.job = brief.job.model_copy(update={"id": job_id})

        if write_to_excel and self.tracker is not None:
            try:
                self.tracker.write_brief_to_tracker(brief)
            except FileNotFoundError:
                pass
        return brief

    def process_job(
        self,
        jd_text: str,
        company: str,
        title: str,
        location: str | None = None,
        url: str | None = None,
        work_model: str | None = None,
        country: str | None = None,
        write_excel: bool = False,
    ) -> ApplicationBrief:
        """Convenience entry point retaining the UI's existing argument names."""
        return self.execute(
            company=company,
            title=title,
            description=jd_text,
            location=location,
            country=country,
            work_model=work_model,
            official_url=url,
            write_to_excel=write_excel,
        )

    def attach_people_and_outreach(
        self,
        brief: ApplicationBrief,
        people: list[PersonTarget],
        outreach: list[OutreachRecord],
    ) -> ApplicationBrief:
        if self.repository is None:
            raise RuntimeError("A repository is required to save people and outreach.")
        if brief.job.id is None:
            raise ValueError("Brief must be persisted before attaching people. Call process_job first.")

        saved_people = [
            person.model_copy(update={"id": self.repository.save_person(brief.job.id, person)})
            for person in people
        ]
        saved_outreach = []
        for record in outreach:
            record = record.model_copy(update={"job_id": brief.job.id})
            record_id = self.repository.save_outreach(record)
            saved_outreach.append(record.model_copy(update={"id": record_id}))
        return brief.model_copy(update={"people": saved_people, "outreach": saved_outreach})

    @staticmethod
    def _build_positioning(fit, gate, ats) -> str:
        tier_label = {
            "tier_1": "Strong Pursue — Tier 1",
            "tier_2": "Pursue — Tier 2",
            "tier_3": "Selective Pursue — Tier 3",
            "do_not_pursue": "Do Not Pursue",
            "barrier": "⚠ Barrier — resolve before pursuing",
        }.get(fit.tier.value, fit.tier.value)
        ats_label = f"ATS Readiness: {ats.readiness:.0f}%" if ats else ""
        barriers_label = f"Barriers: {'; '.join(gate.barriers)}" if gate and gate.barriers else ""
        return " | ".join(part for part in (tier_label, ats_label, barriers_label) if part)

    @staticmethod
    def _determine_next_action(fit, gate) -> str:
        if gate and gate.barriers:
            return "Resolve barriers before pursuing: " + gate.barriers[0]
        return {
            "tier_1": "Apply + research hiring chain + draft outreach",
            "tier_2": "Apply + review ATS gaps + targeted outreach",
            "tier_3": "Apply if bandwidth permits; minimal outreach",
            "do_not_pursue": "Archive — does not meet minimum fit threshold",
            "barrier": "Do not apply until barriers are resolved",
        }.get(fit.tier.value, "Review results and decide.")
