"""
Pydantic v2 domain models for the Job Search Operating Agent.
All scores are calculated deterministically in Python; no model prose is trusted for numeric output.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Confidence(str, Enum):
    confirmed = "confirmed"
    high = "high"
    medium = "medium"
    low = "low"


class PursuitTier(str, Enum):
    tier1 = "tier_1"
    tier2 = "tier_2"
    tier3 = "tier_3"
    do_not_pursue = "do_not_pursue"
    barrier = "barrier"


class KeywordAction(str, Enum):
    keep = "KEEP"
    add = "ADD"
    strengthen = "STRENGTHEN"
    do_not_add = "DO_NOT_ADD"


class OpenStatus(str, Enum):
    open = "OPEN"
    closed = "CLOSED"
    unknown = "UNKNOWN"


class OutreachApproval(str, Enum):
    pending = "pending"
    approved = "approved"
    edited = "edited"
    skipped = "skipped"


class PersonType(str, Enum):
    hiring_manager = "hiring_manager"
    recruiter = "recruiter"
    hm_manager = "hm_manager"
    functional_leader = "functional_leader"
    functional_peer = "functional_peer"
    warm_connector = "warm_connector"
    internal_advocate = "internal_advocate"


class ConflictResolution(str, Enum):
    pending = "pending"
    accepted_local = "accepted_local"
    accepted_provider = "accepted_provider"
    merged = "merged"
    ignored = "ignored"


# ---------------------------------------------------------------------------
# Evidence Library
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    """Represents one verified STAR evidence entry from evidence_library.json."""
    evidence_id: str = Field(alias="id")
    employer: str
    role: Optional[str] = None
    initiative: Optional[str] = None
    period: Optional[str] = None
    capabilities: list[str] = []
    evidence: Optional[str] = None           # free-text description
    claim: str = ""                          # primary claim string (derived)
    safe_claims: list[str] = []
    unsafe_claims: list[str] = []
    metrics: list[str] = []
    technologies: list[str] = []
    keywords: list[str] = []
    source: Optional[str] = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def derive_claim(self) -> "EvidenceItem":
        if not self.claim and self.evidence:
            self.claim = self.evidence
        elif not self.claim and self.safe_claims:
            self.claim = self.safe_claims[0]
        if not self.keywords:
            self.keywords = list(self.capabilities)
        return self


# ---------------------------------------------------------------------------
# Candidate Profile
# ---------------------------------------------------------------------------

class CandidateProfile(BaseModel):
    candidate_id: str
    name: str
    location: str
    headline: str
    summary: str
    education: list[str] = []
    certifications: list[str] = []
    core_capabilities: list[str] = []
    target_role_families: list[str] = []
    avoid_or_selective: list[str] = []
    geography: dict[str, Any] = {}
    constraints: list[str] = []


# ---------------------------------------------------------------------------
# Job Record
# ---------------------------------------------------------------------------

class JobRecord(BaseModel):
    """A discovered / user-entered job posting."""
    id: Optional[int] = None
    company: str
    title: str
    job_id: Optional[str] = None
    official_url: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None          # "official_career", "indeed", "linkedin", "manual", etc.
    location: Optional[str] = None
    country: Optional[str] = None
    work_model: Optional[str] = None           # "remote", "hybrid", "on-site"
    posted_date: Optional[date] = None
    verified_at: Optional[datetime] = None
    status: OpenStatus = OpenStatus.unknown
    description: str
    role_family: Optional[str] = None
    seniority: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# JD Parsing
# ---------------------------------------------------------------------------

class Requirement(BaseModel):
    text: str
    importance: Literal["critical", "important", "supporting"]
    category: str


class ParsedJD(BaseModel):
    role_family: str
    seniority: Optional[str] = None
    must_haves: list[Requirement] = []
    preferred: list[Requirement] = []
    keywords: list[Requirement] = []
    reporting_clues: list[str] = []
    location_auth_clues: list[str] = []
    company_clues: list[str] = []
    raw_extracted: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Hard Gates
# ---------------------------------------------------------------------------

class HardGateResult(BaseModel):
    passed: bool
    barriers: list[str] = []
    authorization_status: Optional[str] = None
    location_status: Optional[str] = None
    profession_match: Optional[str] = None
    mandatory_credential_status: Optional[str] = None
    company_exclusion: Optional[str] = None


# ---------------------------------------------------------------------------
# Strategic Fit
# ---------------------------------------------------------------------------

class DimensionScore(BaseModel):
    score: int = Field(ge=0, le=100)
    rationale: str
    evidence_ids: list[str] = []


class StrategicFit(BaseModel):
    functional: DimensionScore
    seniority: DimensionScore
    domain: DimensionScore
    evidence: DimensionScore
    location_auth: DimensionScore
    competitive: DimensionScore
    relationship: DimensionScore
    weighted_score: float
    tier: PursuitTier
    barriers: list[str] = []


# ---------------------------------------------------------------------------
# ATS Analysis
# ---------------------------------------------------------------------------

class KeywordMatch(BaseModel):
    keyword: str
    importance: Literal["critical", "important", "supporting"]
    category: str
    exact_match: bool = False
    semantic_match: bool = False
    evidence_ids: list[str] = []
    action: KeywordAction
    rationale: str

    @field_validator("evidence_ids")
    @classmethod
    def add_requires_evidence(cls, v: list[str], info: Any) -> list[str]:
        return v


class ATSAssessment(BaseModel):
    readiness: float
    critical_coverage: float
    important_coverage: float
    evidence_coverage: float
    placement_score: float = 0.0
    role_alignment_score: float = 0.0
    matches: list[KeywordMatch] = []
    resume_version: Optional[str] = None

    @property
    def missing_critical(self) -> list[str]:
        return [m.keyword for m in self.matches
                if m.importance == "critical" and not m.exact_match and not m.semantic_match]

    @property
    def keywords_to_add(self) -> list[str]:
        return [m.keyword for m in self.matches if m.action == KeywordAction.add]

    @property
    def unsupported_keywords(self) -> list[str]:
        return [m.keyword for m in self.matches if m.action == KeywordAction.do_not_add]


# ---------------------------------------------------------------------------
# Evidence Mapping
# ---------------------------------------------------------------------------

class EvidenceMapping(BaseModel):
    requirement: str
    evidence_ids: list[str] = []
    strength: Literal["strong", "medium", "weak", "none"] = "none"
    safe_wording: Optional[str] = None
    is_supported: bool = False


# ---------------------------------------------------------------------------
# People & Outreach
# ---------------------------------------------------------------------------

class PersonTarget(BaseModel):
    id: Optional[int] = None
    name: str
    current_title: str
    company: str
    person_type: PersonType
    relationship_to_job: str
    relationship_status: Literal["confirmed", "inferred"] = "inferred"
    confidence: Confidence
    source_url: Optional[str] = None
    source_summary: Optional[str] = None
    checked_at: Optional[datetime] = None
    connection_path: Optional[str] = None
    outreach_priority: int = Field(default=99, ge=1, le=99)
    message_objective: Optional[str] = None
    draft_message: Optional[str] = None
    channel: Optional[str] = None
    email: Optional[str] = None


class OutreachRecord(BaseModel):
    id: Optional[int] = None
    job_id: Optional[int] = None
    person_id: Optional[int] = None
    person_name: Optional[str] = None
    channel: Optional[str] = None
    objective: Optional[str] = None
    draft: Optional[str] = None
    evidence_ids: list[str] = []
    approval_status: OutreachApproval = OutreachApproval.pending
    contacted_at: Optional[datetime] = None
    response: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    created_at: Optional[datetime] = None
    recipient_email: Optional[str] = None
    subject: Optional[str] = None


# ---------------------------------------------------------------------------
# Application Record
# ---------------------------------------------------------------------------

class ApplicationRecord(BaseModel):
    id: Optional[int] = None
    job_id: Optional[int] = None
    applied_at: Optional[datetime] = None
    resume_version: Optional[str] = None
    channel: Optional[str] = None
    status: str = "draft"
    status_source: Optional[str] = None
    status_checked_at: Optional[datetime] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Sync / Reconciliation
# ---------------------------------------------------------------------------

class SyncConflict(BaseModel):
    id: Optional[int] = None
    provider: str
    external_id: str
    local_record_id: Optional[int] = None
    field: str
    local_value: Optional[str] = None
    provider_value: Optional[str] = None
    detected_at: Optional[datetime] = None
    resolution_status: ConflictResolution = ConflictResolution.pending
    resolution_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level Application Brief
# ---------------------------------------------------------------------------

class ApplicationBrief(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    job: JobRecord
    parsed_jd: Optional[ParsedJD] = None
    gate: Optional[HardGateResult] = None
    fit: Optional[StrategicFit] = None
    ats: Optional[ATSAssessment] = None
    evidence_map: list[EvidenceMapping] = []
    people: list[PersonTarget] = []
    outreach: list[OutreachRecord] = []
    positioning: Optional[str] = None
    next_action: Optional[str] = None
    created_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_reloaded_submodels(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for k, v in list(data.items()):
                if hasattr(v, "model_dump"):
                    data[k] = v.model_dump()
                elif isinstance(v, list):
                    data[k] = [x.model_dump() if hasattr(x, "model_dump") else x for x in v]
        return data
