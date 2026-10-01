"""
JD Parser — deterministic keyword extractor + optional LLM-backed enrichment.

Supports two modes:
  1. Pasted JD text (always available — no external calls).
  2. URL fetching via an injected adapter (optional, fails gracefully).

Structured output is validated against ParsedJD; no model prose is trusted for
numeric weights or keyword importance assignments.
"""
from __future__ import annotations

import re
from typing import Optional, Protocol

from app.models import ParsedJD, Requirement

# ---------------------------------------------------------------------------
# Keyword taxonomy — deterministic, maintained centrally
# ---------------------------------------------------------------------------

_CRITICAL_KEYWORDS: list[tuple[str, str]] = [
    # (keyword, category)
    ("technical program management", "core"),
    ("portfolio management", "core"),
    ("program governance", "core"),
    ("roadmap", "planning"),
    ("risk management", "core"),
    ("stakeholder management", "core"),
    ("cross-functional", "core"),
    ("agile", "methodology"),
    ("safe", "methodology"),
    ("lean portfolio management", "methodology"),
    ("lpm", "methodology"),
    ("jira", "tooling"),
    ("confluence", "tooling"),
    ("OKR", "planning"),
    ("capacity planning", "planning"),
    ("resource planning", "planning"),
    ("dependency management", "planning"),
    ("delivery management", "core"),
    ("program manager", "title"),
    ("TPM", "title"),
    ("technical program manager", "title"),
]

_IMPORTANT_KEYWORDS: list[tuple[str, str]] = [
    ("AI", "domain"),
    ("machine learning", "domain"),
    ("data platform", "domain"),
    ("cloud", "domain"),
    ("cloud modernization", "domain"),
    ("platform modernization", "domain"),
    ("servicenow", "tooling"),
    ("executive stakeholder", "stakeholder"),
    ("vendor governance", "governance"),
    ("financial management", "finance"),
    ("TCO", "finance"),
    ("budget", "finance"),
    ("P&L", "finance"),
    ("transformation", "domain"),
    ("operating model", "governance"),
    ("process improvement", "core"),
    ("process re-engineering", "core"),
    ("KPI", "planning"),
    ("metrics", "planning"),
    ("senior", "seniority"),
    ("lead", "seniority"),
    ("principal", "seniority"),
    ("director", "seniority"),
]

_SUPPORTING_KEYWORDS: list[tuple[str, str]] = [
    ("e-commerce", "domain"),
    ("telecom", "domain"),
    ("public sector", "domain"),
    ("procurement", "domain"),
    ("contract lifecycle", "domain"),
    ("data quality", "domain"),
    ("catalog", "domain"),
    ("ontology", "domain"),
    ("automation", "domain"),
    ("MBA", "education"),
    ("scrum master", "methodology"),
    ("SAFe", "methodology"),
    ("sprint", "methodology"),
    ("kanban", "methodology"),
]

# Hard-gate signals
_US_WORK_AUTH_SIGNALS = [
    "must be authorized to work in the united states",
    "authorized to work in the us",
    "us citizen",
    "us citizens only",
    "no sponsorship",
    "no visa sponsorship",
    "u.s. work authorization required",
]

_EXCLUDED_COMPANIES = {"amazon", "cgi"}

_SENIORITY_PATTERNS = [
    (r"\b(staff|principal|distinguished)\b", "principal"),
    (r"\b(senior|sr\.?)\b", "senior"),
    (r"\b(lead|manager|director)\b", "lead/director"),
    (r"\b(junior|associate|entry.level)\b", "junior"),
]

_ROLE_FAMILY_KEYWORDS: dict[str, list[str]] = {
    "Technical Program Management": [
        "technical program manager", "TPM", "program manager", "program management",
    ],
    "Portfolio Management": [
        "portfolio manager", "portfolio management", "portfolio governance",
        "portfolio director",
    ],
    "AI/Data Program": [
        "AI program", "AI portfolio", "data platform", "AI transformation",
        "machine learning program", "AI operations",
    ],
    "Engineering Operations": [
        "engineering operations", "product operations", "engineering program",
        "platform operations",
    ],
    "Technology Transformation": [
        "transformation", "modernization", "cloud program", "technology transformation",
    ],
}


# ---------------------------------------------------------------------------
# URL-fetching adapter protocol (optional)
# ---------------------------------------------------------------------------

class JDFetchAdapter(Protocol):
    def fetch(self, url: str) -> str:
        """Return raw JD text from a URL. Raise on failure."""
        ...


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_jd(
    text: Optional[str] = None,
    url: Optional[str] = None,
    fetch_adapter: Optional[JDFetchAdapter] = None,
    company: Optional[str] = None,
) -> ParsedJD:
    """
    Parse a job description from pasted text or URL.

    Args:
        text: Pasted JD text.
        url: JD URL. Requires fetch_adapter if text is not provided.
        fetch_adapter: Optional adapter to fetch JD from URL.
        company: Company name (used for hard-gate company-exclusion check).

    Returns:
        ParsedJD with deterministically extracted keywords and clues.
    """
    if not text and url:
        if fetch_adapter is None:
            raise ValueError(
                "URL provided but no fetch_adapter available. "
                "Paste the JD text manually or configure an HTTP adapter."
            )
        text = fetch_adapter.fetch(url)

    if not text:
        raise ValueError("Provide either 'text' (pasted JD) or 'url' with a fetch_adapter.")

    lower = text.lower()

    # --- Role family ---
    role_family = "Technical Program Management"  # default
    for family, signals in _ROLE_FAMILY_KEYWORDS.items():
        if any(s.lower() in lower for s in signals):
            role_family = family
            break

    # --- Seniority ---
    seniority: Optional[str] = None
    for pattern, label in _SENIORITY_PATTERNS:
        if re.search(pattern, lower):
            seniority = label
            break

    # --- Keyword extraction ---
    def _build_requirements(
        pairs: list[tuple[str, str]], importance: str
    ) -> list[Requirement]:
        found = []
        for kw, cat in pairs:
            if kw.lower() in lower:
                found.append(Requirement(text=kw, importance=importance, category=cat))  # type: ignore[arg-type]
        return found

    must_haves = _build_requirements(_CRITICAL_KEYWORDS, "critical")
    preferred = _build_requirements(_IMPORTANT_KEYWORDS, "important")
    supporting = _build_requirements(_SUPPORTING_KEYWORDS, "supporting")

    # --- Clues ---
    auth_clues = [s for s in _US_WORK_AUTH_SIGNALS if s in lower]
    location_clues = _extract_location_clues(lower)
    company_clues = _extract_company_clues(lower, company)
    reporting_clues = _extract_reporting_clues(lower)

    return ParsedJD(
        role_family=role_family,
        seniority=seniority,
        must_haves=must_haves,
        preferred=preferred,
        keywords=must_haves + preferred + supporting,
        reporting_clues=reporting_clues,
        location_auth_clues=auth_clues + location_clues,
        company_clues=company_clues,
        raw_extracted={
            "character_count": len(text),
            "word_count": len(text.split()),
        },
    )


# ---------------------------------------------------------------------------
# Clue extractors
# ---------------------------------------------------------------------------

def _extract_location_clues(lower: str) -> list[str]:
    clues = []
    if "canada" in lower or "canadian" in lower:
        clues.append("canada_mentioned")
    if "toronto" in lower:
        clues.append("toronto_mentioned")
    if "remote" in lower:
        clues.append("remote_ok")
    if "hybrid" in lower:
        clues.append("hybrid")
    if "on-site" in lower or "onsite" in lower or "in-office" in lower:
        clues.append("on_site")
    if "relocation" in lower:
        clues.append("relocation_available")
    return clues


def _extract_company_clues(lower: str, company: Optional[str]) -> list[str]:
    clues = []
    if company:
        co_lower = company.strip().lower()
        if any(excl in co_lower for excl in _EXCLUDED_COMPANIES):
            clues.append(f"company_excluded:{company}")
    return clues


def _extract_reporting_clues(lower: str) -> list[str]:
    clues = []
    patterns = [
        ("vp", "reports_to_vp"),
        ("chief", "reports_to_c_level"),
        ("cto", "reports_to_cto"),
        ("cio", "reports_to_cio"),
        ("director", "director_level"),
        ("svp", "reports_to_svp"),
    ]
    for trigger, label in patterns:
        if trigger in lower:
            clues.append(label)
    return clues
