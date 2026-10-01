"""
Gate engine — deterministic hard-gate evaluation.

Returns a fully populated HardGateResult. Rules are explicit Python conditionals;
no model prose is trusted for gate decisions.
"""
from __future__ import annotations

from app.models import HardGateResult, JobRecord, ParsedJD

# Companies the candidate must never target
_EXCLUDED_COMPANIES = {"amazon", "cgi"}

# Work-auth barrier signals (US-only roles)
_US_WORK_AUTH_SIGNALS = [
    "must be authorized to work in the united states",
    "authorized to work in the us",
    "us citizens only",
    "no sponsorship",
    "no visa sponsorship",
    "u.s. work authorization required",
    "must be a us citizen",
    "no h1b",
]

# Roles the candidate is not qualified for / should avoid
_INELIGIBLE_ROLE_SIGNALS = [
    "hands-on software engineer",
    "software development engineer",
    "ml engineer",
    "machine learning engineer",
    "data scientist",
    "enterprise architect",
    "solution architect",
]

# Mandatory credentials that would block the candidate
_MANDATORY_CRED_SIGNALS = [
    "pmp required",
    "pmp certification required",
    "cissp required",
    "active secret clearance",
    "top secret clearance",
    "security clearance required",
    "bar admission required",
    "medical license required",
]


def evaluate(
    job: JobRecord,
    jd: ParsedJD,
    candidate_profile: dict,
) -> HardGateResult:
    """
    Evaluate hard gates for a job against the candidate profile.

    Returns HardGateResult with passed=False if any barrier is unresolved.
    """
    barriers: list[str] = []
    authorization_status: str = "eligible"
    location_status: str = "acceptable"
    profession_match: str = "match"
    mandatory_credential_status: str = "ok"
    company_exclusion: str | None = None

    full_text = (
        job.description
        + " "
        + " ".join(jd.location_auth_clues)
        + " "
        + " ".join(jd.company_clues)
    ).lower()

    # --- Company exclusion ---
    company_lower = job.company.strip().lower()
    for excl in _EXCLUDED_COMPANIES:
        if excl in company_lower:
            company_exclusion = f"Excluded company: {job.company}"
            barriers.append(company_exclusion)
            break
    # Also catch from JD clues (company passed in metadata)
    if not company_exclusion:
        for clue in jd.company_clues:
            if clue.startswith("company_excluded:"):
                company_exclusion = f"Excluded company from JD clues: {clue}"
                barriers.append(company_exclusion)
                break

    # --- Work-authorization / U.S.-only ---
    # The candidate is Canadian; flag if role requires U.S. authorization
    # unless the profile has explicit US authorization or constraint override.
    geography = candidate_profile.get("geography", {})
    secondary_geo = " ".join(geography.get("secondary", [])).lower()
    us_auth_available = "united states" in secondary_geo or "u.s." in secondary_geo

    us_barrier_found = any(s in full_text for s in _US_WORK_AUTH_SIGNALS)
    if us_barrier_found and not us_auth_available:
        authorization_status = "barrier:us_work_auth"
        barriers.append("Potential U.S. work-authorization barrier — no sponsorship stated")
    elif us_barrier_found:
        authorization_status = "flagged:verify_sponsorship"

    # --- Location: remote check ---
    location_auth_clues = jd.location_auth_clues
    if job.country and job.country.lower() in ("us", "usa", "united states", "u.s.", "u.s.a.") and not us_auth_available:
        if "remote_ok" not in location_auth_clues and "canada_mentioned" not in location_auth_clues:
            location_status = "barrier:us_location"
            barriers.append("Role appears US-located with no remote/Canada option indicated")

    # --- Profession match ---
    jd_lower = job.description.lower()
    for signal in _INELIGIBLE_ROLE_SIGNALS:
        if signal in jd_lower:
            profession_match = f"possible_mismatch:{signal}"
            barriers.append(
                f"Role may require hands-on technical skills outside candidate profile: '{signal}'"
            )
            break

    # --- Mandatory credentials ---
    for cred in _MANDATORY_CRED_SIGNALS:
        if cred in jd_lower:
            mandatory_credential_status = f"missing:{cred}"
            barriers.append(f"Mandatory credential candidate does not hold: '{cred}'")
            break

    return HardGateResult(
        passed=len(barriers) == 0,
        barriers=barriers,
        authorization_status=authorization_status,
        location_status=location_status,
        profession_match=profession_match,
        mandatory_credential_status=mandatory_credential_status,
        company_exclusion=company_exclusion,
    )


# ---------------------------------------------------------------------------
# Backward-compat alias (pre-refactor callers used evaluate_gates(job, jd))
# ---------------------------------------------------------------------------

def evaluate_gates(
    job: "JobRecord",
    jd: "ParsedJD",
    candidate_profile: dict | None = None,
) -> "HardGateResult":
    """Legacy 2-arg wrapper; prefer evaluate(job, jd, candidate_profile)."""
    import json
    from pathlib import Path

    if candidate_profile is None:
        profile_path = Path(__file__).parent.parent.parent / "data" / "candidate_profile.json"
        if profile_path.exists():
            with open(profile_path) as f:
                candidate_profile = json.load(f)
        else:
            candidate_profile = {}
    return evaluate(job, jd, candidate_profile)

