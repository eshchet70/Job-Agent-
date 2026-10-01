"""
Main orchestrator — wires the full analysis pipeline.
Order: dedupe → parse → gate → fit → ATS → evidence map → people → outreach → persist.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db import init_db, repository
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
    tracker_writer,
)
from app.services.evidence_loader import load_evidence_library

# Ensure DB tables exist on first import
init_db()

from pathlib import Path

MASTER_RESUME_PATH = Path(__file__).resolve().parent.parent / "data" / "master_resume.txt"

# Approximate candidate resume text (fallback for ATS keyword matching).
CANDIDATE_RESUME_SYNOPSIS = """
Senior Technical Program Manager and Portfolio Leader with 20+ years experience.
Technical program management, portfolio management, program governance, roadmap planning,
dependency management, risk management, capacity and resource planning,
executive stakeholder management, cross-functional delivery, AI and data initiatives,
cloud and platform modernization, ServiceNow, Agile, SAFe, Lean Portfolio Management,
vendor governance, financial analysis, TCO, process re-engineering.
Bell Canada: Led application TCO discovery across 400+ applications, 60+ stakeholders,
seven data systems. Portfolio governance, intake, long-range planning cycles, Agile delivery.
Payment platform modernization with six enterprise architects.
Amazon: Managed Hardlines catalog, ontology, data quality programs with data scientists,
ontologists, 10+ engineers. Seller compliance program reduced non-compliant listings by 20%.
IBM: CLM and procurement integration reduced review time by 30%, improved accuracy by 15%.
Enterprise webmaster program, automation tooling, public sector health and human services.
MBA Rotman School of Management. B.S. Computer Information Systems.
SAFe Lean Portfolio Management. SAFe Advanced Scrum Master.
"""


def load_master_resume(allow_fallback: bool = False) -> str:
    """Load the candidate's master resume text from data/master_resume.txt if available."""
    if MASTER_RESUME_PATH.exists():
        try:
            content = MASTER_RESUME_PATH.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass
    if allow_fallback:
        return CANDIDATE_RESUME_SYNOPSIS.strip()
    return ""


def save_master_resume(text: str) -> None:
    """Persist the candidate's updated master resume text to data/master_resume.txt."""
    MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_RESUME_PATH.write_text(text.strip(), encoding="utf-8")


def analyze_job(
    company: str,
    title: str,
    description: str,
    location: Optional[str] = None,
    country: Optional[str] = None,
    work_model: Optional[str] = None,
    official_url: Optional[str] = None,
    source_type: str = "manual",
    people_list: Optional[list[dict]] = None,
    save_to_db: bool = True,
    write_to_excel: bool = False,
) -> ApplicationBrief:
    """
    Full analysis pipeline for a single job description.

    Args:
        company: Company name.
        title: Role title.
        description: Full JD text (pasted or fetched).
        location, country, work_model: Optional location info.
        official_url: Official career page URL if known.
        source_type: Portal source identifier.
        people_list: Optional pre-supplied people targets (list of dicts).
        save_to_db: Persist to SQLite.
        write_to_excel: Also sync to Excel tracker.

    Returns:
        Populated ApplicationBrief.
    """
    # ── 1. Deduplication ───────────────────────────────────────────────────
    existing_id = repository.find_duplicate_job(company, title)
    if existing_id:
        existing_brief = repository.get_brief_for_job(existing_id)
        if existing_brief:
            return existing_brief
        existing_job = repository.get_job(existing_id)
        if existing_job:
            return ApplicationBrief(
                job=existing_job,
                next_action="Duplicate detected — see existing record.",
            )

    # ── 2. Build JobRecord ─────────────────────────────────────────────────
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

    # ── 3. Parse JD ────────────────────────────────────────────────────────
    parsed_jd = jd_parser.parse_jd(description, company=company)
    job.role_family = parsed_jd.role_family
    job.seniority = parsed_jd.seniority

    # ── 4. Hard Gates ──────────────────────────────────────────────────────
    gate = gate_engine.evaluate_gates(job, parsed_jd)

    # ── 5. Strategic Fit ───────────────────────────────────────────────────
    fit = fit_estimator.estimate_fit(job, parsed_jd, gate)

    # ── 6. ATS Analysis ────────────────────────────────────────────────────
    evidence_library = load_evidence_library()
    all_keywords = parsed_jd.keywords + parsed_jd.must_haves + parsed_jd.preferred
    current_resume_text = load_master_resume(allow_fallback=True)
    ats = ats_engine.assess(
        keywords=all_keywords,
        resume_text=current_resume_text,
        evidence=evidence_library,
        role_title=title,
    )

    # ── 7. Evidence Mapping ─────────────────────────────────────────────────
    evidence_map = evidence_engine.map_evidence(
        requirements=parsed_jd.must_haves + parsed_jd.preferred,
        evidence=evidence_library,
    )

    # ── 8. People & Outreach ───────────────────────────────────────────────
    people: list[PersonTarget] = []
    outreach: list[OutreachRecord] = []

    if people_list:
        people = people_research.normalize_people(people_list)
        for person in people:
            draft_rec = message_generator.generate_draft(job, person)
            outreach.append(draft_rec)

    # ── 9. Positioning & Next Action ───────────────────────────────────────
    positioning = _build_positioning(fit, gate, ats)
    next_action = _determine_next_action(fit, gate)

    def _dump_or_raw(x):
        return x.model_dump() if hasattr(x, "model_dump") else x

    brief = ApplicationBrief(
        job=_dump_or_raw(job),
        parsed_jd=_dump_or_raw(parsed_jd),
        gate=_dump_or_raw(gate),
        fit=_dump_or_raw(fit),
        ats=_dump_or_raw(ats),
        evidence_map=[_dump_or_raw(e) for e in evidence_map],
        people=[_dump_or_raw(p) for p in people],
        outreach=[_dump_or_raw(o) for o in outreach],
        positioning=positioning,
        next_action=next_action,
        created_at=datetime.now(timezone.utc),
    )

    # ── 10. Persist ────────────────────────────────────────────────────────
    if save_to_db:
        job_id = repository.save_brief(brief)
        brief.job = brief.job.model_copy(update={"id": job_id})

    if write_to_excel:
        try:
            tracker_writer.write_brief_to_tracker(brief)
        except FileNotFoundError:
            pass  # tracker not found; silently skip

    return brief


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_positioning(fit, gate, ats) -> str:
    if not fit:
        return "Analysis pending."
    tier_label = {
        "tier_1": "Strong Pursue — Tier 1",
        "tier_2": "Pursue — Tier 2",
        "tier_3": "Selective Pursue — Tier 3",
        "do_not_pursue": "Do Not Pursue",
        "barrier": "⚠ Barrier — resolve before pursuing",
    }.get(fit.tier.value, fit.tier.value)

    ats_label = f"ATS Readiness: {ats.readiness:.0f}%" if ats else ""
    barriers_label = f"Barriers: {'; '.join(gate.barriers)}" if gate and gate.barriers else ""
    parts = [p for p in [tier_label, ats_label, barriers_label] if p]
    return " | ".join(parts)


def _determine_next_action(fit, gate) -> str:
    if gate and gate.barriers:
        return "Resolve barriers before pursuing: " + gate.barriers[0]
    if not fit:
        return "Complete analysis."
    return {
        "tier_1": "Apply + research hiring chain + draft outreach",
        "tier_2": "Apply + review ATS gaps + targeted outreach",
        "tier_3": "Apply if bandwidth permits; minimal outreach",
        "do_not_pursue": "Archive — does not meet minimum fit threshold",
        "barrier": "Do not apply until barriers are resolved",
    }.get(fit.tier.value, "Review results and decide.")


# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------

def process_job(
    jd_text: str,
    company: str,
    title: str,
    location: str | None = None,
    url: str | None = None,
    work_model: str | None = None,
    country: str | None = None,
    write_excel: bool = False,
) -> "ApplicationBrief":
    """
    Thin wrapper over analyze_job() with keyword-arg names matching the
    Streamlit UI and test fixtures.
    """
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
    from app.services.evidence_loader import load_evidence_library
    return load_evidence_library()


def attach_people_and_outreach(
    brief: "ApplicationBrief",
    people: list,
    outreach: list,
) -> "ApplicationBrief":
    """
    Persist people and outreach records and attach them to the brief.
    No message is sent automatically — all outreach stays at approval_status=pending.
    """
    if brief.job.id is None:
        raise ValueError("Brief must be persisted before attaching people. Call process_job first.")

    saved_people = []
    for person in people:
        pid = repository.save_person(brief.job.id, person)
        saved_people.append(person.model_copy(update={"id": pid}))

    saved_outreach = []
    for rec in outreach:
        rec = rec.model_copy(update={"job_id": brief.job.id})
        oid = repository.save_outreach(rec)
        saved_outreach.append(rec.model_copy(update={"id": oid}))

    return brief.model_copy(update={"people": saved_people, "outreach": saved_outreach})


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
    """
    Tailor resume for the given job, updating the current role experience,
    summary, competencies, and tools with missing keywords.
    """
    from app.services import resume_tailor
    if master_resume_text is None:
        master_resume_text = load_master_resume(allow_fallback=True)
    evidence_library = load_evidence()
    return resume_tailor.tailor_resume(
        master_resume_text=master_resume_text,
        job=job,
        parsed_jd=parsed_jd,
        selected_keywords=selected_keywords,
        update_current_role=update_current_role,
        update_summary=update_summary,
        update_competencies=update_competencies,
        update_tools=update_tools,
        evidence=evidence_library,
    )


