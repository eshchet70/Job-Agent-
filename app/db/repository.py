"""Repository layer — clean CRUD interface over the SQLite ORM."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.database import (
    AuditLogDB,
    ATSAssessmentDB,
    ApplicationDB,
    HardGateDB,
    JobDB,
    OutreachDB,
    PersonDB,
    StrategicFitDB,
    SyncConflictDB,
    get_session,
)
from app.models import (
    ApplicationBrief,
    ApplicationRecord,
    ATSAssessment,
    HardGateResult,
    JobRecord,
    OpenStatus,
    OutreachApproval,
    OutreachRecord,
    PersonTarget,
    StrategicFit,
    SyncConflict,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _audit(session: Session, action: str, entity_type: str = "",
           entity_id: Optional[int] = None, detail: str = "") -> None:
    session.add(AuditLogDB(
        action=action, entity_type=entity_type,
        entity_id=entity_id, detail=detail
    ))


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

def save_job(job: JobRecord, session: Optional[Session] = None) -> int:
    """Persist a JobRecord; returns the assigned id."""
    own = session is None
    s = session or get_session()
    try:
        row = JobDB(
            company=job.company, title=job.title, job_id=job.job_id,
            official_url=job.official_url, source_url=job.source_url,
            source_type=job.source_type, location=job.location,
            country=job.country, work_model=job.work_model,
            posted_date=str(job.posted_date) if job.posted_date else None,
            verified_at=job.verified_at, status=job.status.value,
            description=job.description, role_family=job.role_family,
            seniority=job.seniority,
        )
        s.add(row)
        s.flush()
        _audit(s, "save_job", "job", row.id, f"{job.company} — {job.title}")
        if own:
            s.commit()
        return row.id
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


def get_job(job_id: int) -> Optional[JobRecord]:
    s = get_session()
    try:
        row = s.get(JobDB, job_id)
        if not row:
            return None
        return _job_row_to_model(row)
    finally:
        s.close()


def list_jobs(limit: int = 100) -> list[JobRecord]:
    s = get_session()
    try:
        rows = s.query(JobDB).order_by(JobDB.created_at.desc()).limit(limit).all()
        return [_job_row_to_model(r) for r in rows]
    finally:
        s.close()


def find_duplicate_job(company: str, title: str) -> Optional[int]:
    """Return id of an existing job with the same company+title, or None."""
    s = get_session()
    try:
        row = (s.query(JobDB)
               .filter(JobDB.company.ilike(company), JobDB.title.ilike(title))
               .first())
        return row.id if row else None
    finally:
        s.close()


def _job_row_to_model(row: JobDB) -> JobRecord:
    return JobRecord(
        id=row.id, company=row.company, title=row.title, job_id=row.job_id,
        official_url=row.official_url, source_url=row.source_url,
        source_type=row.source_type, location=row.location, country=row.country,
        work_model=row.work_model, verified_at=row.verified_at,
        status=OpenStatus(row.status), description=row.description,
        role_family=row.role_family, seniority=row.seniority,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Hard Gate
# ---------------------------------------------------------------------------

def save_gate(job_id: int, gate: HardGateResult, session: Optional[Session] = None) -> None:
    own = session is None
    s = session or get_session()
    try:
        row = HardGateDB(
            job_id=job_id, passed=gate.passed,
            authorization_status=gate.authorization_status,
            location_status=gate.location_status,
            profession_match=gate.profession_match,
            mandatory_credential_status=gate.mandatory_credential_status,
            company_exclusion=gate.company_exclusion,
        )
        row.barriers = gate.barriers
        s.add(row)
        if own:
            s.commit()
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


# ---------------------------------------------------------------------------
# Strategic Fit
# ---------------------------------------------------------------------------

def save_fit(job_id: int, fit: StrategicFit, session: Optional[Session] = None) -> None:
    own = session is None
    s = session or get_session()
    try:
        row = StrategicFitDB(
            job_id=job_id,
            functional_score=fit.functional.score,
            seniority_score=fit.seniority.score,
            domain_score=fit.domain.score,
            evidence_score=fit.evidence.score,
            location_auth_score=fit.location_auth.score,
            competitive_score=fit.competitive.score,
            relationship_score=fit.relationship.score,
            weighted_score=fit.weighted_score,
            tier=fit.tier.value,
            dimensions_json=fit.model_dump_json(),
            barriers_json=json.dumps(fit.barriers),
        )
        s.add(row)
        if own:
            s.commit()
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


def get_fit_for_job(job_id: int) -> Optional[dict]:
    """Retrieve strategic fit summary (tier, weighted_score, barriers) for a job."""
    s = get_session()
    try:
        row = s.query(StrategicFitDB).filter_by(job_id=job_id).first()
        if not row:
            return None
        return {
            "tier": row.tier,
            "weighted_score": row.weighted_score,
            "barriers": json.loads(row.barriers_json or "[]"),
        }
    finally:
        s.close()


def update_job_tier(job_id: int, tier: str, score: Optional[float] = None) -> bool:
    """Manually update or assign the pursuit tier and score for a job."""
    s = get_session()
    try:
        row = s.query(StrategicFitDB).filter_by(job_id=job_id).first()
        if not row:
            row = StrategicFitDB(
                job_id=job_id,
                tier=tier,
                weighted_score=score if score is not None else 70.0,
                functional_score=70,
                seniority_score=70,
                domain_score=70,
                evidence_score=70,
                location_auth_score=70,
                competitive_score=70,
                relationship_score=70,
                dimensions_json="{}",
                barriers_json="[]",
            )
            s.add(row)
        else:
            row.tier = tier
            if score is not None:
                row.weighted_score = score
        _audit(s, "update_tier", "strategic_fit", job_id, f"Tier updated to {tier}")
        s.commit()
        return True
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# ATS Assessment
# ---------------------------------------------------------------------------

def save_ats(job_id: int, ats: ATSAssessment, session: Optional[Session] = None) -> None:
    own = session is None
    s = session or get_session()
    try:
        row = ATSAssessmentDB(
            job_id=job_id,
            readiness=ats.readiness,
            critical_coverage=ats.critical_coverage,
            important_coverage=ats.important_coverage,
            evidence_coverage=ats.evidence_coverage,
            placement_score=ats.placement_score,
            role_alignment_score=ats.role_alignment_score,
            matches_json=ats.model_dump_json(),
            resume_version=ats.resume_version,
        )
        s.add(row)
        if own:
            s.commit()
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


def get_ats_for_job(job_id: int) -> Optional[dict]:
    """Retrieve ATS summary (readiness, coverage) for a job."""
    s = get_session()
    try:
        row = s.query(ATSAssessmentDB).filter_by(job_id=job_id).first()
        if not row:
            return None
        return {
            "readiness": row.readiness,
            "critical_coverage": row.critical_coverage,
            "important_coverage": row.important_coverage,
        }
    finally:
        s.close()


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

def save_person(job_id: int, person: PersonTarget,
                session: Optional[Session] = None) -> int:
    own = session is None
    s = session or get_session()
    try:
        # Check if person already exists for this job to prevent duplicates
        existing = s.query(PersonDB).filter(
            PersonDB.job_id == job_id,
            PersonDB.name.ilike(person.name.strip()),
        ).first()
        if existing:
            existing.current_title = person.current_title
            existing.company = person.company
            existing.person_type = person.person_type.value
            existing.relationship_to_job = person.relationship_to_job
            existing.confidence = person.confidence.value
            if person.source_url:
                existing.source_url = person.source_url
            if person.outreach_priority:
                existing.outreach_priority = person.outreach_priority
            if person.email and hasattr(existing, "email"):
                existing.email = person.email
            if own:
                s.commit()
            return existing.id

        kwargs = {
            "job_id": job_id,
            "name": person.name,
            "current_title": person.current_title,
            "company": person.company,
            "person_type": person.person_type.value,
            "relationship_to_job": person.relationship_to_job,
            "relationship_status": person.relationship_status,
            "confidence": person.confidence.value,
            "source_url": person.source_url,
            "source_summary": person.source_summary,
            "checked_at": person.checked_at,
            "connection_path": person.connection_path,
            "outreach_priority": person.outreach_priority,
            "message_objective": person.message_objective,
            "draft_message": person.draft_message,
            "channel": person.channel,
        }
        try:
            row = PersonDB(**kwargs, email=person.email)
        except TypeError:
            row = PersonDB(**kwargs)
            if hasattr(row, "email"):
                row.email = person.email

        s.add(row)
        s.flush()
        if hasattr(row, "email") and person.email and not getattr(row, "email", None):
            row.email = person.email
        if own:
            s.commit()
        return row.id
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


def update_person_email(person_id: int, email: str) -> None:
    """Update email address for a person."""
    s = get_session()
    try:
        row = s.get(PersonDB, person_id)
        if not row:
            return
        row.email = email
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def delete_person(person_id: int) -> bool:
    """Delete a person from the database and cascade delete their outreach records."""
    s = get_session()
    try:
        row = s.get(PersonDB, person_id)
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()



def get_people_for_job(job_id: int) -> list[PersonTarget]:
    s = get_session()
    try:
        rows = (s.query(PersonDB)
                .filter(PersonDB.job_id == job_id)
                .order_by(PersonDB.outreach_priority)
                .all())
        return [_person_row_to_model(r) for r in rows]
    finally:
        s.close()


def _person_row_to_model(row: PersonDB) -> PersonTarget:
    from app.models import Confidence, PersonType
    return PersonTarget(
        id=row.id, name=row.name, current_title=row.current_title,
        company=row.company, person_type=PersonType(row.person_type),
        relationship_to_job=row.relationship_to_job,
        relationship_status=row.relationship_status,
        confidence=Confidence(row.confidence),
        source_url=row.source_url, source_summary=row.source_summary,
        checked_at=row.checked_at, connection_path=row.connection_path,
        outreach_priority=row.outreach_priority,
        message_objective=row.message_objective,
        draft_message=row.draft_message, channel=row.channel,
        email=getattr(row, "email", None),
    )


# ---------------------------------------------------------------------------
# Outreach
# ---------------------------------------------------------------------------

def save_outreach(outreach: OutreachRecord, session: Optional[Session] = None) -> int:
    own = session is None
    s = session or get_session()
    try:
        if outreach.person_id:
            existing = s.query(OutreachDB).filter_by(
                job_id=outreach.job_id,
                person_id=outreach.person_id,
            ).first()
            if existing:
                existing.draft = outreach.draft
                existing.objective = outreach.objective
                existing.subject = outreach.subject
                existing.channel = outreach.channel
                if outreach.recipient_email:
                    existing.recipient_email = outreach.recipient_email
                if own:
                    s.commit()
                return existing.id

        row = OutreachDB(
            job_id=outreach.job_id, person_id=outreach.person_id,
            person_name=outreach.person_name, channel=outreach.channel,
            objective=outreach.objective, draft=outreach.draft,
            evidence_ids_json=json.dumps(outreach.evidence_ids),
            approval_status=outreach.approval_status.value,
            contacted_at=outreach.contacted_at, response=outreach.response,
            next_action=outreach.next_action,
            next_action_date=str(outreach.next_action_date) if outreach.next_action_date else None,
            recipient_email=outreach.recipient_email,
            subject=outreach.subject,
        )
        s.add(row)
        s.flush()
        if own:
            s.commit()
        return row.id
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


def update_outreach_status(outreach_id: int, status: OutreachApproval,
                           edited_draft: Optional[str] = None) -> None:
    s = get_session()
    try:
        row = s.get(OutreachDB, outreach_id)
        if not row:
            return
        row.approval_status = status.value
        if edited_draft:
            row.draft = edited_draft
        _audit(s, "update_outreach_status", "outreach", outreach_id, status.value)
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def record_email_sent(outreach_id: int, recipient_email: str, subject: str,
                      sent_body: Optional[str] = None) -> None:
    """Record that an email was sent directly from the application."""
    s = get_session()
    try:
        row = s.get(OutreachDB, outreach_id)
        if not row:
            return
        if row.approval_status != OutreachApproval.approved.value:
            raise PermissionError(
                f"Email dispatch rejected: Outreach record {outreach_id} (Person: '{row.person_name}') "
                f"is in '{row.approval_status}' status. Only approved outreach messages can be sent."
            )
        row.channel = "email"
        row.contacted_at = datetime.now(timezone.utc)
        row.recipient_email = recipient_email
        row.subject = subject
        if sent_body:
            row.draft = sent_body
        _audit(s, "send_email", "outreach", outreach_id, f"Sent email to {recipient_email}: '{subject}'")
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_outreach_for_job(job_id: int) -> list[OutreachRecord]:
    s = get_session()
    try:
        rows = s.query(OutreachDB).filter(OutreachDB.job_id == job_id).all()
        return [_outreach_row_to_model(r) for r in rows]
    finally:
        s.close()


def _outreach_row_to_model(row: OutreachDB) -> OutreachRecord:
    return OutreachRecord(
        id=row.id, job_id=row.job_id, person_id=row.person_id,
        person_name=row.person_name, channel=row.channel,
        objective=row.objective, draft=row.draft,
        evidence_ids=json.loads(row.evidence_ids_json or "[]"),
        approval_status=OutreachApproval(row.approval_status),
        contacted_at=row.contacted_at, response=row.response,
        next_action=row.next_action,
        created_at=row.created_at,
        recipient_email=getattr(row, "recipient_email", None),
        subject=getattr(row, "subject", None),
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def save_application(app_rec: ApplicationRecord,
                     session: Optional[Session] = None) -> int:
    own = session is None
    s = session or get_session()
    try:
        row = ApplicationDB(
            job_id=app_rec.job_id, applied_at=app_rec.applied_at,
            resume_version=app_rec.resume_version, channel=app_rec.channel,
            status=app_rec.status, status_source=app_rec.status_source,
            status_checked_at=app_rec.status_checked_at,
            next_action=app_rec.next_action,
            next_action_date=str(app_rec.next_action_date) if app_rec.next_action_date else None,
            notes=app_rec.notes,
        )
        s.add(row)
        s.flush()
        if own:
            s.commit()
        return row.id
    except Exception:
        if own:
            s.rollback()
        raise
    finally:
        if own:
            s.close()


def update_application_status(
    job_id: int,
    status: str = "applied",
    applied_at: Optional[datetime] = None,
    channel: Optional[str] = "company_site",
    status_source: Optional[str] = "linkedin",
    notes: Optional[str] = None,
    next_action: Optional[str] = None,
) -> int:
    """Update or create application record for a job."""
    s = get_session()
    try:
        app_row = s.query(ApplicationDB).filter(ApplicationDB.job_id == job_id).first()
        if not app_row:
            app_row = ApplicationDB(job_id=job_id)
            s.add(app_row)

        app_row.status = status
        if applied_at is not None:
            app_row.applied_at = applied_at
        if channel is not None:
            app_row.channel = channel
        if status_source is not None:
            app_row.status_source = status_source
        app_row.status_checked_at = datetime.utcnow()
        if notes is not None:
            app_row.notes = notes
        if next_action is not None:
            app_row.next_action = next_action

        # Also mark Job as OPEN
        job_row = s.query(JobDB).filter(JobDB.id == job_id).first()
        if job_row:
            job_row.status = "OPEN"

        s.commit()
        return app_row.id
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_application_for_job(job_id: int) -> Optional[ApplicationRecord]:
    """Retrieve application record for a specific job."""
    s = get_session()
    try:
        row = s.query(ApplicationDB).filter(ApplicationDB.job_id == job_id).first()
        if not row:
            return None
        return ApplicationRecord(
            id=row.id,
            job_id=row.job_id,
            applied_at=row.applied_at,
            resume_version=row.resume_version,
            channel=row.channel,
            status=row.status or "draft",
            status_source=row.status_source,
            status_checked_at=row.status_checked_at,
            next_action=row.next_action,
            notes=row.notes,
        )
    finally:
        s.close()



# ---------------------------------------------------------------------------
# Sync Conflicts
# ---------------------------------------------------------------------------

def save_conflict(conflict: SyncConflict) -> int:
    s = get_session()
    try:
        row = SyncConflictDB(
            provider=conflict.provider, external_id=conflict.external_id,
            local_record_id=conflict.local_record_id, field=conflict.field,
            local_value=conflict.local_value, provider_value=conflict.provider_value,
            resolution_status=conflict.resolution_status.value,
            resolution_note=conflict.resolution_note,
        )
        s.add(row)
        s.flush()
        s.commit()
        return row.id
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_pending_conflicts() -> list[SyncConflict]:
    from app.models import ConflictResolution
    s = get_session()
    try:
        rows = (s.query(SyncConflictDB)
                .filter(SyncConflictDB.resolution_status == "pending")
                .order_by(SyncConflictDB.detected_at.desc())
                .all())
        return [
            SyncConflict(
                id=r.id, provider=r.provider, external_id=r.external_id,
                local_record_id=r.local_record_id, field=r.field,
                local_value=r.local_value, provider_value=r.provider_value,
                detected_at=r.detected_at,
                resolution_status=ConflictResolution(r.resolution_status),
            )
            for r in rows
        ]
    finally:
        s.close()


def resolve_conflict(conflict_id: int, resolution: str, note: str = "") -> None:
    s = get_session()
    try:
        row = s.get(SyncConflictDB, conflict_id)
        if row:
            row.resolution_status = resolution
            row.resolution_note = note
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Dashboard / Analytics
# ---------------------------------------------------------------------------

def get_dashboard_stats() -> dict:
    s = get_session()
    try:
        total = s.query(JobDB).count()
        tier_rows = (s.query(StrategicFitDB.tier,
                             __import__("sqlalchemy").func.count(StrategicFitDB.id))
                     .group_by(StrategicFitDB.tier).all())
        tiers = {row[0]: row[1] for row in tier_rows}

        avg_ats = s.query(
            __import__("sqlalchemy").func.avg(ATSAssessmentDB.readiness)
        ).scalar() or 0.0

        outreach_pending = (s.query(OutreachDB)
                            .filter(OutreachDB.approval_status == "pending")
                            .count())
        conflicts_pending = (s.query(SyncConflictDB)
                             .filter(SyncConflictDB.resolution_status == "pending")
                             .count())

        return {
            "total_jobs": total,
            "by_tier": tiers,
            "avg_ats_readiness": round(avg_ats, 1),
            "outreach_pending": outreach_pending,
            "conflicts_pending": conflicts_pending,
        }
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Full Brief Saver
# ---------------------------------------------------------------------------

def save_brief(brief: ApplicationBrief) -> int:
    """Persist all components of an ApplicationBrief in a single transaction."""
    s = get_session()
    try:
        job_id = save_job(brief.job, session=s)
        brief.job = brief.job.model_copy(update={"id": job_id})

        if brief.gate:
            save_gate(job_id, brief.gate, session=s)
        if brief.fit:
            save_fit(job_id, brief.fit, session=s)
        if brief.ats:
            save_ats(job_id, brief.ats, session=s)

        for person in brief.people:
            pid = save_person(job_id, person, session=s)
            person = person.model_copy(update={"id": pid})

        for outreach in brief.outreach:
            outreach = outreach.model_copy(update={"job_id": job_id})
            save_outreach(outreach, session=s)

        app_rec = ApplicationRecord(job_id=job_id, next_action=brief.next_action)
        save_application(app_rec, session=s)

        _audit(s, "save_brief", "job", job_id,
               f"Brief saved for {brief.job.company} — {brief.job.title}")
        s.commit()
        return job_id
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_brief_for_job(job_id: int) -> Optional[ApplicationBrief]:
    """Reconstruct an ApplicationBrief from persisted database records."""
    job = get_job(job_id)
    if not job:
        return None
    s = get_session()
    try:
        from app.services import jd_parser, evidence_engine
        from app.services.evidence_loader import load_evidence_library

        parsed_jd = None
        if job.description:
            parsed_jd = jd_parser.parse_jd(job.description, company=job.company)

        gate = None
        gate_row = s.query(HardGateDB).filter_by(job_id=job_id).first()
        if gate_row:
            gate = HardGateResult(
                passed=gate_row.passed,
                barriers=gate_row.barriers,
                authorization_status=gate_row.authorization_status,
                location_status=gate_row.location_status,
                profession_match=gate_row.profession_match,
                mandatory_credential_status=gate_row.mandatory_credential_status,
                company_exclusion=gate_row.company_exclusion,
            )

        fit = None
        fit_row = s.query(StrategicFitDB).filter_by(job_id=job_id).first()
        if fit_row and fit_row.dimensions_json:
            fit = StrategicFit.model_validate_json(fit_row.dimensions_json)

        ats = None
        ats_row = s.query(ATSAssessmentDB).filter_by(job_id=job_id).first()
        if ats_row and ats_row.matches_json:
            ats = ATSAssessment.model_validate_json(ats_row.matches_json)

        evidence_map = []
        if parsed_jd:
            evidence_library = load_evidence_library()
            evidence_map = evidence_engine.map_evidence(
                requirements=parsed_jd.must_haves + parsed_jd.preferred,
                evidence=evidence_library,
            )

        people = get_people_for_job(job_id)
        outreach = get_outreach_for_job(job_id)

        app_rec = get_application_for_job(job_id)
        next_action = app_rec.next_action if app_rec else None

        return ApplicationBrief(
            job=job,
            parsed_jd=parsed_jd.model_dump() if parsed_jd and hasattr(parsed_jd, "model_dump") else parsed_jd,
            gate=gate.model_dump() if gate and hasattr(gate, "model_dump") else gate,
            fit=fit.model_dump() if fit and hasattr(fit, "model_dump") else fit,
            ats=ats.model_dump() if ats and hasattr(ats, "model_dump") else ats,
            evidence_map=[e.model_dump() if hasattr(e, "model_dump") else e for e in evidence_map],
            people=people,
            outreach=outreach,
            next_action=next_action,
        )
    finally:
        s.close()

