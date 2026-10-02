"""
Interview Agent — records, verifies, and assesses interview data for submitted applications.

Workflow:
  1. User logs each interview round (phone screen, technical, panel, etc.) with notes
  2. Agent verifies internal consistency of the record (missing info, contradictions)
  3. Claude analyzes the full interview record against the original job requirements
     and produces a structured assessment:
       - Performance by dimension (communication, technical fit, cultural fit, etc.)
       - Signals: positive, neutral, concerning
       - Likelihood of progressing
       - Recommended follow-up actions
       - Gaps to address if another round is scheduled

Persistence: data/interviews/{job_id}.json
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("interview_agent")

ROOT = Path(__file__).resolve().parent.parent.parent
INTERVIEWS_DIR = ROOT / "data" / "interviews"
DEFAULT_MODEL = "claude-sonnet-4-5"


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

class RoundType(str, Enum):
    recruiter_screen   = "recruiter_screen"
    hiring_manager     = "hiring_manager"
    technical          = "technical"
    behavioral         = "behavioral"
    panel              = "panel"
    case_study         = "case_study"
    executive          = "executive"
    reference_check    = "reference_check"
    offer_discussion   = "offer_discussion"
    other              = "other"


class RoundOutcome(str, Enum):
    passed     = "passed"
    rejected   = "rejected"
    pending    = "pending"   # awaiting decision
    unknown    = "unknown"


@dataclass
class InterviewRound:
    """One interview round in the process."""
    round_number: int
    round_type: str                  # RoundType value
    date: str                        # ISO date string
    interviewer_name: str = ""
    interviewer_title: str = ""
    duration_minutes: int = 0
    format: str = ""                 # "video", "phone", "on-site", "async"
    topics_covered: list[str] = field(default_factory=list)
    questions_asked: list[str] = field(default_factory=list)
    candidate_notes: str = ""        # User's own notes / how they felt it went
    outcome: str = RoundOutcome.pending.value
    outcome_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "round_number": self.round_number,
            "round_type": self.round_type,
            "date": self.date,
            "interviewer_name": self.interviewer_name,
            "interviewer_title": self.interviewer_title,
            "duration_minutes": self.duration_minutes,
            "format": self.format,
            "topics_covered": self.topics_covered,
            "questions_asked": self.questions_asked,
            "candidate_notes": self.candidate_notes,
            "outcome": self.outcome,
            "outcome_notes": self.outcome_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InterviewRound":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class InterviewRecord:
    """Full interview history for one job application."""
    job_id: str
    company: str
    title: str
    url: str
    overall_status: str = "in_progress"   # in_progress | offer | rejected | withdrawn
    rounds: list[InterviewRound] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    # Cached assessment from last Claude run
    last_assessment: Optional[dict] = None
    last_assessed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "company": self.company,
            "title": self.title,
            "url": self.url,
            "overall_status": self.overall_status,
            "rounds": [r.to_dict() for r in self.rounds],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_assessment": self.last_assessment,
            "last_assessed_at": self.last_assessed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InterviewRecord":
        rounds = [InterviewRound.from_dict(r) for r in d.get("rounds", [])]
        return cls(
            job_id=d["job_id"],
            company=d["company"],
            title=d["title"],
            url=d.get("url", ""),
            overall_status=d.get("overall_status", "in_progress"),
            rounds=rounds,
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            last_assessment=d.get("last_assessment"),
            last_assessed_at=d.get("last_assessed_at", ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Assessment Schema (returned by Claude)
# ─────────────────────────────────────────────────────────────────────────────

ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_impression": {
            "type": "string",
            "description": "1-2 sentence honest summary of how the interview process is going"
        },
        "likelihood_to_proceed": {
            "type": "string",
            "enum": ["very_likely", "likely", "uncertain", "unlikely", "very_unlikely"],
            "description": "Assessment of candidate's likelihood of advancing or receiving offer"
        },
        "likelihood_rationale": {
            "type": "string",
            "description": "Why you assessed this likelihood"
        },
        "dimension_scores": {
            "type": "object",
            "description": "Score 0-10 per dimension with rationale",
            "properties": {
                "communication": {"type": "object", "properties": {
                    "score": {"type": "integer"}, "rationale": {"type": "string"}
                }},
                "technical_fit": {"type": "object", "properties": {
                    "score": {"type": "integer"}, "rationale": {"type": "string"}
                }},
                "leadership_fit": {"type": "object", "properties": {
                    "score": {"type": "integer"}, "rationale": {"type": "string"}
                }},
                "cultural_fit": {"type": "object", "properties": {
                    "score": {"type": "integer"}, "rationale": {"type": "string"}
                }},
                "candidate_preparedness": {"type": "object", "properties": {
                    "score": {"type": "integer"}, "rationale": {"type": "string"}
                }},
            }
        },
        "positive_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific positive signals from the interview record"
        },
        "concerning_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Red flags, hesitations, or areas of concern"
        },
        "neutral_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Observations that are neither clearly positive nor negative"
        },
        "gaps_identified": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skills, experiences, or topics where the candidate may have fallen short"
        },
        "strengths_demonstrated": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Areas where the candidate clearly shone"
        },
        "follow_up_actions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete next steps the candidate should take"
        },
        "next_round_prep": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific things to prepare if another round is scheduled"
        },
        "thank_you_note_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key points to include in a post-interview thank-you note"
        },
        "process_stage": {
            "type": "string",
            "description": "Where in the hiring funnel the candidate appears to be"
        },
        "estimated_timeline": {
            "type": "string",
            "description": "Estimated timeline to decision based on typical patterns"
        },
    },
    "required": [
        "overall_impression", "likelihood_to_proceed", "likelihood_rationale",
        "dimension_scores", "positive_signals", "concerning_signals",
        "gaps_identified", "strengths_demonstrated", "follow_up_actions",
    ]
}


# ─────────────────────────────────────────────────────────────────────────────
# Verification Logic (deterministic — no LLM)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completeness_pct: int = 0


def verify_record(record: InterviewRecord) -> VerificationResult:
    """
    Run deterministic checks on the interview record.
    No LLM required — purely structural validation.
    """
    warnings: list[str] = []
    errors: list[str] = []
    fields_present = 0
    fields_total = 0

    if not record.rounds:
        errors.append("No interview rounds logged yet.")
        return VerificationResult(is_valid=False, errors=errors, completeness_pct=0)

    for i, r in enumerate(record.rounds, 1):
        rname = f"Round {i} ({r.round_type})"

        # Date
        fields_total += 1
        if r.date:
            fields_present += 1
        else:
            warnings.append(f"{rname}: Date not recorded.")

        # Interviewer
        fields_total += 1
        if r.interviewer_name:
            fields_present += 1
        else:
            warnings.append(f"{rname}: Interviewer name not recorded — important for thank-you notes.")

        # Duration
        fields_total += 1
        if r.duration_minutes > 0:
            fields_present += 1
        else:
            warnings.append(f"{rname}: Duration not recorded.")

        # Notes
        fields_total += 1
        if r.candidate_notes and len(r.candidate_notes) > 30:
            fields_present += 1
        elif r.candidate_notes:
            warnings.append(f"{rname}: Notes are very brief — add more detail for a better assessment.")
        else:
            warnings.append(f"{rname}: No candidate notes recorded — hard to assess without them.")

        # Topics / Questions
        fields_total += 1
        if r.topics_covered or r.questions_asked:
            fields_present += 1
        else:
            warnings.append(f"{rname}: No topics or questions logged.")

        # Outcome
        fields_total += 1
        if r.outcome and r.outcome != RoundOutcome.unknown.value:
            fields_present += 1
        else:
            warnings.append(f"{rname}: Outcome not recorded (passed / rejected / pending).")

        # Consistency checks
        if r.outcome == RoundOutcome.rejected.value and i < len(record.rounds):
            errors.append(
                f"{rname}: Marked as rejected but more rounds follow — verify this is correct."
            )

    completeness = int((fields_present / fields_total) * 100) if fields_total else 0
    is_valid = len(errors) == 0 and completeness >= 40

    return VerificationResult(
        is_valid=is_valid,
        warnings=warnings,
        errors=errors,
        completeness_pct=completeness,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main Interview Agent
# ─────────────────────────────────────────────────────────────────────────────

class InterviewAgent:
    """
    Records, verifies, and AI-assesses job interview data.

    Usage:
        agent = InterviewAgent()

        # Load or create a record
        rec = agent.get_or_create(job_id, company, title, url)

        # Add a round
        agent.add_round(rec, round_data_dict)

        # Verify structural completeness
        verification = agent.verify(rec)

        # Run full AI assessment (requires ANTHROPIC_API_KEY)
        assessment = agent.assess(rec, jd_text=jd_text, must_haves=must_haves)
    """

    def __init__(self, model: str = None):
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

    # ── Record Management ─────────────────────────────────────────────────

    def get_or_create(
        self, job_id: str, company: str, title: str, url: str = ""
    ) -> InterviewRecord:
        existing = self.load(job_id)
        if existing:
            return existing
        now = _now()
        rec = InterviewRecord(
            job_id=job_id, company=company, title=title, url=url,
            created_at=now, updated_at=now,
        )
        self.save(rec)
        return rec

    def add_round(self, record: InterviewRecord, round_data: dict) -> InterviewRound:
        """Add a new interview round to the record."""
        round_number = len(record.rounds) + 1
        r = InterviewRound(
            round_number=round_number,
            round_type=round_data.get("round_type", RoundType.other.value),
            date=round_data.get("date", ""),
            interviewer_name=round_data.get("interviewer_name", ""),
            interviewer_title=round_data.get("interviewer_title", ""),
            duration_minutes=int(round_data.get("duration_minutes", 0)),
            format=round_data.get("format", ""),
            topics_covered=round_data.get("topics_covered", []),
            questions_asked=round_data.get("questions_asked", []),
            candidate_notes=round_data.get("candidate_notes", ""),
            outcome=round_data.get("outcome", RoundOutcome.pending.value),
            outcome_notes=round_data.get("outcome_notes", ""),
        )
        record.rounds.append(r)
        record.updated_at = _now()
        self.save(record)
        log.info("Added round %d to %s — %s", round_number, record.company, record.title)
        return r

    def update_round(self, record: InterviewRecord, round_number: int, updates: dict) -> None:
        """Update fields on an existing round."""
        for r in record.rounds:
            if r.round_number == round_number:
                for k, v in updates.items():
                    if hasattr(r, k):
                        setattr(r, k, v)
        record.updated_at = _now()
        self.save(record)

    def set_overall_status(self, record: InterviewRecord, status: str) -> None:
        record.overall_status = status
        record.updated_at = _now()
        self.save(record)

    # ── Verification ──────────────────────────────────────────────────────

    def verify(self, record: InterviewRecord) -> VerificationResult:
        return verify_record(record)

    # ── AI Assessment ─────────────────────────────────────────────────────

    def assess(
        self,
        record: InterviewRecord,
        jd_text: str = "",
        must_haves: list[str] = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        Run a Claude-powered assessment of the full interview record.

        Args:
            record:        The full InterviewRecord
            jd_text:       Original job description text (improves assessment accuracy)
            must_haves:    List of must-have requirements from the JD
            force_refresh: Re-run even if a cached assessment exists

        Returns:
            Assessment dict matching ASSESSMENT_SCHEMA
        """
        if not force_refresh and record.last_assessment and record.last_assessed_at:
            log.info("Returning cached assessment for %s", record.job_id)
            return record.last_assessment

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._placeholder_assessment(record)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = self._build_assessment_prompt(record, jd_text, must_haves or [])

            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=1,   # Required for extended thinking
                thinking={
                    "type": "enabled",
                    "budget_tokens": 2000,
                },
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": "interview_assessment",
                    "description": "Structured assessment of the interview record",
                    "input_schema": ASSESSMENT_SCHEMA,
                }],
                tool_choice={"type": "tool", "name": "interview_assessment"},
            )

            # Extract tool result
            assessment = None
            for block in response.content:
                if block.type == "tool_use" and block.name == "interview_assessment":
                    assessment = block.input
                    break

            if assessment:
                record.last_assessment = assessment
                record.last_assessed_at = _now()
                self.save(record)
                log.info("Assessment complete for %s — %s", record.company, record.title)
                return assessment

        except anthropic.AuthenticationError:
            log.warning("Invalid ANTHROPIC_API_KEY — returning placeholder assessment")
        except Exception as exc:
            log.error("Assessment failed: %s", exc, exc_info=True)

        return self._placeholder_assessment(record)

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self, record: InterviewRecord) -> None:
        INTERVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        self._path(record.job_id).write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def load(self, job_id: str) -> Optional[InterviewRecord]:
        path = self._path(job_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return InterviewRecord.from_dict(data)
            except Exception as exc:
                log.error("Failed to load interview record %s: %s", job_id, exc)
        return None

    def list_all(self) -> list[InterviewRecord]:
        """Return all saved interview records."""
        records = []
        if INTERVIEWS_DIR.exists():
            for p in sorted(INTERVIEWS_DIR.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    records.append(InterviewRecord.from_dict(data))
                except Exception:
                    pass
        return records

    # ── Internal helpers ──────────────────────────────────────────────────

    def _path(self, job_id: str) -> Path:
        import re
        safe = re.sub(r"[^\w]", "_", job_id)[:80]
        return INTERVIEWS_DIR / f"{safe}.json"

    def _build_assessment_prompt(
        self, record: InterviewRecord, jd_text: str, must_haves: list[str]
    ) -> str:
        rounds_text = ""
        for r in record.rounds:
            rounds_text += f"""
Round {r.round_number}: {r.round_type.replace('_', ' ').title()}
  Date: {r.date or 'not recorded'}
  Interviewer: {r.interviewer_name or 'unknown'} ({r.interviewer_title or 'unknown title'})
  Duration: {r.duration_minutes or 'unknown'} minutes  |  Format: {r.format or 'unknown'}
  Topics Covered: {', '.join(r.topics_covered) if r.topics_covered else 'not recorded'}
  Questions Asked: {chr(10) + '    - ' + (chr(10) + '    - ').join(r.questions_asked) if r.questions_asked else 'not recorded'}
  Candidate Notes: {r.candidate_notes or 'none'}
  Round Outcome: {r.outcome}
  Outcome Notes: {r.outcome_notes or 'none'}
"""

        must_haves_text = "\n".join(f"  - {m}" for m in must_haves) if must_haves else "  Not provided"

        return f"""You are an experienced executive career coach and talent acquisition expert.
You are analyzing the interview record for this candidate and job, and providing a rigorous, honest assessment.

=== JOB ===
Company: {record.company}
Role: {record.title}
URL: {record.url}

=== JOB REQUIREMENTS (Must-Haves) ===
{must_haves_text}

=== JOB DESCRIPTION (excerpt) ===
{(jd_text or 'Not provided')[:3000]}

=== INTERVIEW RECORD ===
Overall Status: {record.overall_status}
Total Rounds Completed: {len(record.rounds)}
{rounds_text}

=== YOUR TASK ===
Analyze this interview record holistically. Be honest and specific — this is for the candidate's own reflection and improvement, not for the company. Call out concerns clearly.

Assess:
1. How well did the candidate demonstrate alignment with the must-have requirements?
2. What signals in the interviewer behavior or questions suggest how the candidate is perceived?
3. What specific actions should the candidate take next?
4. If there is another round: what should the candidate prepare for?

Use the interview_assessment tool to return your structured assessment."""

    def _placeholder_assessment(self, record: InterviewRecord) -> dict:
        """Deterministic fallback when no API key is configured."""
        rounds = record.rounds
        passed = [r for r in rounds if r.outcome == "passed"]
        pending = [r for r in rounds if r.outcome == "pending"]
        rejected = [r for r in rounds if r.outcome == "rejected"]

        if rejected:
            likelihood = "very_unlikely"
        elif len(passed) >= 3:
            likelihood = "likely"
        elif len(passed) >= 1:
            likelihood = "uncertain"
        else:
            likelihood = "uncertain"

        signals = []
        for r in passed:
            signals.append(f"Round {r.round_number} ({r.round_type}) passed")

        notes_snippets = [r.candidate_notes[:100] for r in rounds if r.candidate_notes]
        has_notes = len(notes_snippets) > 0

        return {
            "overall_impression": (
                f"{len(rounds)} round(s) logged for {record.company}. "
                f"{len(passed)} passed, {len(pending)} pending, {len(rejected)} rejected. "
                "Add ANTHROPIC_API_KEY for a detailed AI-powered assessment."
            ),
            "likelihood_to_proceed": likelihood,
            "likelihood_rationale": f"Based on {len(passed)} passed rounds and {len(pending)} pending.",
            "dimension_scores": {
                "communication": {"score": 0, "rationale": "Requires AI assessment — add ANTHROPIC_API_KEY"},
                "technical_fit": {"score": 0, "rationale": "Requires AI assessment"},
                "leadership_fit": {"score": 0, "rationale": "Requires AI assessment"},
                "cultural_fit": {"score": 0, "rationale": "Requires AI assessment"},
                "candidate_preparedness": {"score": 0, "rationale": "Requires AI assessment"},
            },
            "positive_signals": signals,
            "concerning_signals": [f"Round {r.round_number} marked rejected" for r in rejected],
            "neutral_signals": [],
            "gaps_identified": [] if has_notes else ["No candidate notes recorded — add interview notes for AI assessment"],
            "strengths_demonstrated": [],
            "follow_up_actions": [
                "Send a thank-you note within 24 hours of each round",
                "Follow up with the recruiter if no response in 5 business days",
                "Add ANTHROPIC_API_KEY to enable AI-powered assessment",
            ],
            "next_round_prep": [],
            "thank_you_note_points": [
                f"Thank the interviewer for their time at {record.company}",
                "Reiterate your enthusiasm for the role",
                "Reference a specific topic discussed in the interview",
            ],
            "process_stage": f"Round {len(rounds)} of unknown total",
            "estimated_timeline": "Typically 1-2 weeks for a decision after the final round",
            "_placeholder": True,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
