"""Backward-compatible entry points for job-analysis application services."""
from __future__ import annotations

from app.application import create_job_analysis_service
from app.models import ApplicationBrief, JobRecord, ParsedJD
from app.services.evidence_loader import load_evidence_library
from app.services.resume_store import load_master_resume, save_master_resume

__all__ = [
    "analyze_job",
    "attach_people_and_outreach",
    "load_evidence",
    "load_master_resume",
    "process_job",
    "save_master_resume",
    "tailor_resume_for_job",
]


def analyze_job(
    company: str,
    title: str,
    description: str,
    location: str | None = None,
    country: str | None = None,
    work_model: str | None = None,
    official_url: str | None = None,
    source_type: str = "manual",
    people_list: list[dict] | None = None,
    save_to_db: bool = True,
    write_to_excel: bool = False,
) -> ApplicationBrief:
    """Compatibility wrapper; set ``save_to_db=False`` for side-effect-free analysis."""
    service = create_job_analysis_service()
    kwargs = {
        "company": company,
        "title": title,
        "description": description,
        "location": location,
        "country": country,
        "work_model": work_model,
        "official_url": official_url,
        "source_type": source_type,
        "people_list": people_list,
    }
    if save_to_db:
        return service.execute(**kwargs, write_to_excel=write_to_excel)
    brief = service.analyze(**kwargs)
    if write_to_excel:
        service.sync_tracker(brief)
    return brief


def process_job(
    jd_text: str,
    company: str,
    title: str,
    location: str | None = None,
    url: str | None = None,
    work_model: str | None = None,
    country: str | None = None,
    write_excel: bool = False,
) -> ApplicationBrief:
    """Compatibility wrapper with keyword names used by the UI and tests."""
    return analyze_job(
        company=company,
        title=title,
        description=jd_text,
        location=location,
        country=country,
        work_model=work_model,
        official_url=url,
        write_to_excel=write_excel,
    )


def load_evidence() -> list:
    """Return the full evidence library (used by Streamlit UI)."""
    return load_evidence_library()


def attach_people_and_outreach(
    brief: ApplicationBrief,
    people: list,
    outreach: list,
) -> ApplicationBrief:
    """Persist people and outreach records; messages remain pending approval."""
    return create_job_analysis_service().attach_people_and_outreach(brief, people, outreach)


def tailor_resume_for_job(
    job: JobRecord | dict,
    parsed_jd: ParsedJD,
    master_resume_text: str | None = None,
    selected_keywords: list[str] | None = None,
    update_current_role: bool = True,
    update_summary: bool = True,
    update_competencies: bool = True,
    update_tools: bool = True,
) -> tuple[str, dict]:
    """Tailor a resume using the existing evidence-constrained resume engine."""
    from app.services import resume_tailor

    if master_resume_text is None:
        master_resume_text = load_master_resume(allow_fallback=True)
    return resume_tailor.tailor_resume(
        master_resume_text=master_resume_text,
        job=job,
        parsed_jd=parsed_jd,
        selected_keywords=selected_keywords,
        update_current_role=update_current_role,
        update_summary=update_summary,
        update_competencies=update_competencies,
        update_tools=update_tools,
        evidence=load_evidence(),
    )
