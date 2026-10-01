# Data Dictionary

## Job
id, company, title, job_id, official_url, source_url, source_type, posted_date, checked_at, open_status, location, country, work_model, jd_text, role_family, seniority.

## HardGateResult
pass, barrier, reasons[], authorization_status, location_status, profession_match, mandatory_credential_status.

## StrategicFit
functional, seniority, domain, evidence, location_auth, competitive, relationship; each has score 0-100, rationale, evidence_ids[]. weighted_score; tier.

## ATSResult
readiness, critical_coverage, important_coverage, evidence_coverage, placement_score, role_alignment_score; keywords[] where each keyword has term, normalized_term, importance, match_type, evidence_ids[], action.

## Person
name, current_title, company, person_type, relationship_to_job, relationship_status (confirmed/inferred), confidence, source_url, source_summary, checked_at, connection_path, outreach_priority.

## Outreach
job_id, person_id, channel, objective, draft, evidence_ids[], approval_status, contacted_at, response, next_action, next_action_date.

## Application
job_id, applied_at, resume_version, channel, status, status_source, status_checked_at, next_action, next_action_date.

## SyncConflict
provider, external_id, local_record_id, field, local_value, provider_value, detected_at, resolution_status, resolution_note.
