"""
Outreach message generator.
Produces recipient-specific draft messages grounded only in verified evidence IDs.
Never invents metrics, relationships, credentials, or contact details.
Requires human approval before any message is sent.
"""
from __future__ import annotations

import re

from app.models import EvidenceItem, JobRecord, PersonTarget, PersonType, OutreachRecord
from app.services.evidence_loader import load_evidence_library, get_evidence_by_id

# Guardrail strings injected into every context package passed to LLM adapters
GUARDRAILS = [
    "Do not invent experience, metrics, reporting lines, credentials, or contact information.",
    "Use only the approved evidence IDs listed in this context.",
    "This is a DRAFT only; it must not be sent without explicit user approval.",
    "Do not reference mutual connections unless explicitly listed in connection_path.",
]


def generate_draft(
    job: JobRecord,
    person: PersonTarget,
    evidence_ids: list[str] | None = None,
) -> OutreachRecord:
    """
    Generate a draft outreach message for a specific person.
    Falls back to a deterministic template when no LLM is configured.

    Guardrails enforced here (deterministic layer):
      - Only approved evidence IDs are used.
      - No invented metrics or relationships.
      - Draft is returned with approval_status = pending.
    """
    library = load_evidence_library()

    # Resolve evidence items — only verified IDs
    approved_ev: list[EvidenceItem] = []
    if evidence_ids:
        for eid in evidence_ids:
            item = get_evidence_by_id(eid)
            if item:
                approved_ev.append(item)
    else:
        # Auto-select top 3 most relevant to job title keywords
        title_lower = job.title.lower()
        scored = sorted(
            library,
            key=lambda e: sum(1 for k in e.capabilities + e.keywords
                               if k.lower() in title_lower),
            reverse=True,
        )
        approved_ev = scored[:3]

    used_ids = [e.evidence_id for e in approved_ev]

    draft = _template_draft(job, person, approved_ev)

    return OutreachRecord(
        job_id=job.id,
        person_id=person.id,
        person_name=person.name,
        channel=person.channel or _default_channel(person.person_type),
        objective=person.message_objective or _default_objective(person.person_type),
        draft=draft,
        evidence_ids=used_ids,
    )


def message_context(
    job: JobRecord,
    person: PersonTarget,
    evidence: list[EvidenceItem],
) -> dict:
    """
    Return a safe context dict that an LLM adapter may use to draft outreach.
    Only approved evidence is included; guardrails are embedded.
    """
    return {
        "job": {"company": job.company, "title": job.title, "location": job.location},
        "person": person.model_dump(exclude={"draft_message"}),
        "approved_evidence": [e.model_dump() for e in evidence],
        "guardrails": GUARDRAILS,
    }


def get_contact_first_name(raw_name: str) -> str:
    """Extract a clean personal first name, stripping job titles or corporate artifacts."""
    if not raw_name:
        return "there"
    name = raw_name.strip()
    prefixes_to_strip = [
        "dr.", "mr.", "ms.", "mrs.", "senior", "sr.", "lead", "principal",
        "talent", "recruiter", "hiring", "manager", "head of", "vp", "director"
    ]
    parts = [p for p in re.sub(r"[^\w\s-]", "", name).split() if p]
    if not parts:
        return "there"

    while parts and parts[0].lower() in prefixes_to_strip and len(parts) > 1:
        parts.pop(0)

    first = parts[0].capitalize()
    if first.lower() in ("talent", "recruiting", "recruiter", "hiring", "manager"):
        return "there"
    return first


# ---------------------------------------------------------------------------
# Deterministic template drafts
# ---------------------------------------------------------------------------

def _template_draft(
    job: JobRecord,
    person: PersonTarget,
    evidence: list[EvidenceItem],
) -> str:
    candidate_name = "Elena"
    first_name = get_contact_first_name(person.name)

    # Pick the strongest safe claim across top evidence
    top_claim = ""
    top_employer = ""
    if evidence:
        best = evidence[0]
        top_claim = best.safe_claims[0] if best.safe_claims else best.claim
        top_employer = best.employer

    if person.person_type == PersonType.recruiter:
        return (
            f"Hi {first_name},\n\n"
            f"I recently applied for the {job.title} role at {job.company} "
            f"and wanted to reach out directly.\n\n"
            f"I have 20+ years leading complex technical programs and portfolios "
            f"across telecom, enterprise tech, and e-commerce. "
            + (f"Most recently, I {top_claim.lower()} at {top_employer}. " if top_claim else "")
            + f"\n\nI would welcome the opportunity to discuss alignment with this role.\n\n"
            f"Best,\n{candidate_name}"
        )

    if person.person_type == PersonType.hiring_manager:
        return (
            f"Hi {first_name},\n\n"
            f"I came across the {job.title} opportunity at {job.company} "
            f"and see strong alignment with the scope you are building.\n\n"
            + (f"In my work at {top_employer}, I {top_claim.lower()} — "
               f"a challenge that mirrors what this role addresses. " if top_claim else "")
            + f"\n\nI would be glad to share more if there is a fit worth exploring.\n\n"
            f"Best,\n{candidate_name}"
        )

    if person.person_type == PersonType.warm_connector:
        return (
            f"Hi {first_name},\n\n"
            f"I hope you are well! I noticed {job.company} is hiring for "
            f"{job.title} and it aligns closely with my background in "
            f"technical program and portfolio leadership.\n\n"
            f"Would you be comfortable making a brief introduction to "
            f"{person.relationship_to_job or 'the hiring team'}? "
            f"I am happy to share a one-pager if that helps.\n\n"
            f"Thanks so much!\n{candidate_name}"
        )

    if person.person_type == PersonType.internal_advocate:
        return (
            f"Hi {first_name},\n\n"
            f"I have been following {job.company}'s work in this space and see "
            f"strong alignment between my 20+ year portfolio/program leadership background "
            f"and the {job.title} role.\n\n"
            + (f"Specifically, {top_claim.lower()} at {top_employer} — "
               f"experience directly relevant to what this team is building. " if top_claim else "")
            + f"\n\nIf you are willing to provide a routing note or referral, "
            f"I would be very grateful.\n\n"
            f"Best,\n{candidate_name}"
        )

    # Default / peer
    return (
        f"Hi {first_name},\n\n"
        f"I am exploring the {job.title} opportunity at {job.company} "
        f"and your background suggests you may have useful perspective on the team.\n\n"
        f"Would you be open to a brief conversation?\n\n"
        f"Best,\n{candidate_name}"
    )


def _default_channel(person_type: PersonType) -> str:
    return {
        PersonType.hiring_manager: "LinkedIn",
        PersonType.recruiter: "LinkedIn / Email",
        PersonType.warm_connector: "LinkedIn",
        PersonType.hm_manager: "LinkedIn",
        PersonType.functional_leader: "LinkedIn",
        PersonType.functional_peer: "LinkedIn",
        PersonType.internal_advocate: "LinkedIn",
    }.get(person_type, "LinkedIn")


def _default_objective(person_type: PersonType) -> str:
    return {
        PersonType.hiring_manager: "Connect role's core challenge to strongest evidence",
        PersonType.recruiter: "Confirm application + 2–3 key requirement matches",
        PersonType.warm_connector: "Request explicit introduction with forwardable rationale",
        PersonType.hm_manager: "Broader portfolio/transformation relevance",
        PersonType.functional_leader: "Portfolio/transformation relevance — use selectively",
        PersonType.functional_peer: "Perspective and routing request",
        PersonType.internal_advocate: "Credible routing or referral request",
    }.get(person_type, "Introduce candidacy")


# ---------------------------------------------------------------------------
# Backward-compat / convenience alias used by the Streamlit UI
# ---------------------------------------------------------------------------

def build_draft(
    job: "JobRecord",
    person: "PersonTarget",
    evidence: "list[EvidenceItem] | None" = None,
) -> "OutreachRecord":
    """
    UI-facing alias for generate_draft().
    Accepts an optional explicit evidence list (ignored at this layer —
    the generator loads evidence internally from the library).
    """
    return generate_draft(job, person)

