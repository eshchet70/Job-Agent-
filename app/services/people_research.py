"""
People Research service.
Normalizes and ranks hiring-chain targets.
Evidence-grounded; never invents names, emails, or relationships.
"""
from __future__ import annotations

from datetime import datetime

from app.models import (
    Confidence,
    EvidenceItem,
    JobRecord,
    PersonTarget,
    PersonType,
    StrategicFit,
)

# Priority order from hiring-chain-research SKILL.md
PRIORITY_ORDER = [
    PersonType.hiring_manager,
    PersonType.recruiter,
    PersonType.warm_connector,
    PersonType.hm_manager,
    PersonType.functional_leader,
    PersonType.functional_peer,
    PersonType.internal_advocate,
]


def normalize_people(raw: list[dict]) -> list[PersonTarget]:
    """
    Validate and normalize a list of raw person dicts into PersonTarget models.
    Enforces that inferred people are labeled as inferred (never confirmed without source).
    """
    results = []
    for person_dict in raw:
        # Safety: if no source_url and relationship_status is "confirmed", downgrade to inferred
        if not person_dict.get("source_url") and person_dict.get("relationship_status") == "confirmed":
            person_dict["relationship_status"] = "inferred"
        person = PersonTarget.model_validate(person_dict)
        results.append(person)
    return _rank_by_priority(results)


def _rank_by_priority(people: list[PersonTarget]) -> list[PersonTarget]:
    """Sort people by the canonical outreach priority order."""
    def priority_key(p: PersonTarget) -> int:
        try:
            return PRIORITY_ORDER.index(p.person_type)
        except ValueError:
            return 99

    return sorted(people, key=priority_key)


def build_outreach_sequence(
    people: list[PersonTarget],
    job: JobRecord,
    fit: StrategicFit | None = None,
) -> list[dict]:
    """
    Generate outreach sequencing recommendations based on the hiring-chain-research skill spec.
    Day 0: apply; Day 0-1: warm intro if strong path; Day 1-2: recruiter;
    Day 2-4: hiring manager; Day 4-6: peer/advocate selectively;
    Day 7-10: evidence-based follow-up; Day 18-21: reassess; Day 30: archive.
    """
    sequence = []
    day = 0

    for person in people:
        if person.person_type == PersonType.warm_connector and person.confidence in (
            Confidence.confirmed, Confidence.high
        ):
            sequence.append({
                "day": 0 if day == 0 else day + 1,
                "person": person.name,
                "person_type": person.person_type.value,
                "action": "Warm introduction request",
                "channel": person.channel or "LinkedIn / Email",
                "objective": person.message_objective or "Request introduction to hiring team",
                "priority": "high",
            })
            day = max(day, 1)

        elif person.person_type == PersonType.recruiter:
            sequence.append({
                "day": max(day, 1),
                "person": person.name,
                "person_type": person.person_type.value,
                "action": "Recruiter outreach",
                "channel": person.channel or "LinkedIn / Email",
                "objective": person.message_objective or
                             "Confirm application + highlight 2–3 key requirement matches",
                "priority": "high",
            })
            day = max(day, 2)

        elif person.person_type == PersonType.hiring_manager:
            sequence.append({
                "day": max(day, 2),
                "person": person.name,
                "person_type": person.person_type.value,
                "action": "Hiring manager connection",
                "channel": person.channel or "LinkedIn",
                "objective": person.message_objective or
                             "Connect role's core challenge to strongest evidence",
                "priority": "high",
            })
            day = max(day, 4)

        elif person.person_type in (PersonType.functional_peer, PersonType.internal_advocate):
            sequence.append({
                "day": max(day, 4),
                "person": person.name,
                "person_type": person.person_type.value,
                "action": "Selective peer/advocate outreach",
                "channel": person.channel or "LinkedIn",
                "objective": person.message_objective or "Request routing or referral",
                "priority": "medium",
            })
            day = max(day, 6)

        elif person.person_type in (PersonType.hm_manager, PersonType.functional_leader):
            sequence.append({
                "day": max(day, 6),
                "person": person.name,
                "person_type": person.person_type.value,
                "action": "Senior leader outreach (selective)",
                "channel": person.channel or "LinkedIn",
                "objective": person.message_objective or
                             "Portfolio/transformation relevance; use selectively",
                "priority": "low",
            })

    # Add follow-up reminders
    sequence.append({
        "day": 7,
        "person": "Recruiter / Hiring Manager",
        "person_type": "follow_up",
        "action": "Evidence-based follow-up (if no response)",
        "channel": "LinkedIn / Email",
        "objective": "Reference one specific requirement match; keep brief",
        "priority": "medium",
    })
    sequence.append({
        "day": 21,
        "person": "All",
        "person_type": "milestone",
        "action": "Reassess — archive if no response or active signal",
        "channel": "Internal",
        "objective": "Decision checkpoint",
        "priority": "low",
    })

    sequence.sort(key=lambda x: x["day"])
    return sequence
