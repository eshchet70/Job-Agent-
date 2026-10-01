"""
LinkedIn Discovery & Search Strategy Service for the Job Search Operating Agent.

Generates targeted Boolean queries, clean LinkedIn search URLs (optimized for LinkedIn's parser),
Google X-Ray search URLs, and parses LinkedIn profile URLs / snippets into structured PersonTarget models.
Also provides curated, discovered stakeholders for analyzed jobs.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.models import Confidence, JobRecord, PersonTarget, PersonType


@dataclass
class SearchStrategy:
    """A targeted LinkedIn discovery strategy for a specific role archetype."""
    archetype_id: str
    title: str
    target_roles: str
    objective: str
    boolean_query: str
    linkedin_url: str
    google_xray_url: str
    suggested_person_type: PersonType
    suggested_priority: int


def get_candidate_affiliations() -> dict[str, list[str]]:
    """Extract candidate universities and past companies for warm-path searches."""
    affiliations: dict[str, list[str]] = {
        "schools": ["Rotman", "University of Toronto", "University of Northern Colorado"],
        "companies": ["Bell", "Amazon", "IBM", "MegaFon", "Beeline", "jNetX"],
    }
    profile_path = Path(__file__).resolve().parent.parent.parent / "data" / "candidate_profile.json"
    if profile_path.exists():
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            schools = []
            for edu in data.get("education", []):
                for kw in ("Rotman", "University of Toronto", "Northern Colorado", "Colorado"):
                    if kw.lower() in edu.lower() and kw not in schools:
                        schools.append(kw)
            if schools:
                affiliations["schools"] = schools
        except Exception:
            pass
    return affiliations


def _clean_company_name(company: str) -> str:
    """Remove legal entity suffixes for cleaner search queries (e.g. 'Lightspeed Commerce, Inc.' -> 'Lightspeed')."""
    comp = company.strip()
    for suffix in ("Commerce, Inc.", "Commerce Inc", "Commerce", "Inc.", "Inc", "Corp.", "Corp", "LLC", "Ltd.", "Ltd"):
        if comp.endswith(suffix) and len(comp) > len(suffix) + 2:
            comp = comp[:-len(suffix)].strip(",. ")
            break
    return comp or company.strip()


def build_search_strategies(job: JobRecord) -> list[SearchStrategy]:
    """
    Build high-precision LinkedIn and Google X-Ray queries tailored to this job.
    LinkedIn URLs use clean, syntax-safe queries that LinkedIn's native search engine parses cleanly.
    Google X-Ray URLs use full Boolean syntax.
    """
    company_full = (job.company or "").strip()
    company_short = _clean_company_name(company_full)
    title = (job.title or "").strip()
    location = (job.location or "").strip()

    # Clean location for search query (e.g. "Toronto, ON (Remote)" -> "Toronto")
    loc_clean = ""
    for city in ("Toronto", "Montreal", "Vancouver", "Ottawa", "Calgary", "New York", "San Francisco", "Seattle", "Austin", "Boston"):
        if city.lower() in location.lower():
            loc_clean = city
            break

    title_lower = title.lower()

    # ── 1. Hiring Manager Strategy ─────────────────────────────────────────────
    if any(k in title_lower for k in ("tpm", "technical program", "pdlc", "program manager")):
        hm_domains = '("Technical Program" OR "Product Operations" OR "Engineering Operations" OR "PDLC" OR "Program Management")'
        hm_li_keywords = f'{company_short} (Director OR VP) ("Technical Program" OR "Product Operations")'
    elif any(k in title_lower for k in ("product", "product manager")):
        hm_domains = '("Product Management" OR "Product Operations" OR "Product" OR "VP Product")'
        hm_li_keywords = f'{company_short} (Director OR VP) "Product Management"'
    elif any(k in title_lower for k in ("ai", "data", "analytics")):
        hm_domains = '("AI" OR "Data" OR "Enterprise Transformation" OR "Engineering")'
        hm_li_keywords = f'{company_short} (Director OR VP OR Head) (AI OR Data)'
    else:
        hm_domains = f'("{title}")'
        hm_li_keywords = f'{company_short} (Director OR VP) "{title}"'

    hm_seniorities = '("Director" OR "VP" OR "Vice President" OR "Head of" OR "Senior Director")'
    hm_boolean = f'"{company_full}" AND {hm_seniorities} AND {hm_domains}'
    if loc_clean:
        hm_boolean += f' AND "{loc_clean}"'

    # LinkedIn-friendly URL (no nested multi-clause parenthetical ANDs that fail on standard LinkedIn)
    hm_li_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(hm_li_keywords)}&origin=GLOBAL_SEARCH_HEADER"
    
    # Google X-Ray URL (full Boolean syntax)
    hm_xray_query = f'site:linkedin.com/in/ "{company_full}" {hm_seniorities} {hm_domains}'
    if loc_clean:
        hm_xray_query += f' "{loc_clean}"'
    hm_xray_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(hm_xray_query)}"

    strat_hm = SearchStrategy(
        archetype_id="hiring_manager",
        title="🎯 Decision Maker (Likely Hiring Manager)",
        target_roles="Director / VP of Technical Program Management, Product Operations, or Engineering",
        objective="Reach the functional leader who directly owns the problem space and headcount.",
        boolean_query=hm_boolean,
        linkedin_url=hm_li_url,
        google_xray_url=hm_xray_url,
        suggested_person_type=PersonType.hiring_manager,
        suggested_priority=1,
    )

    # ── 2. Recruiter / Talent Acquisition Strategy ─────────────────────────────
    recruiter_titles = '("Technical Recruiter" OR "Talent Acquisition" OR "Recruiter" OR "Talent Partner" OR "Lead Recruiter")'
    rec_boolean = f'"{company_full}" AND {recruiter_titles} AND ("Tech" OR "Product" OR "Engineering")'
    if loc_clean:
        rec_boolean += f' AND "{loc_clean}"'

    rec_li_keywords = f'{company_short} ("Technical Recruiter" OR "Talent Acquisition" OR "Talent Partner")'
    rec_li_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(rec_li_keywords)}&origin=GLOBAL_SEARCH_HEADER"
    
    rec_xray_query = f'site:linkedin.com/in/ "{company_full}" {recruiter_titles}'
    if loc_clean:
        rec_xray_query += f' "{loc_clean}"'
    rec_xray_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(rec_xray_query)}"

    strat_recruiter = SearchStrategy(
        archetype_id="recruiter",
        title="🤝 Gatekeeper (Tech Recruiter / Talent Partner)",
        target_roles="Technical Recruiter, Lead Talent Partner (Engineering/Product), Sourcer",
        objective="Find the talent partner screening candidates and managing the active requisition.",
        boolean_query=rec_boolean,
        linkedin_url=rec_li_url,
        google_xray_url=rec_xray_url,
        suggested_person_type=PersonType.recruiter,
        suggested_priority=2,
    )

    # ── 3. Peers & Functional Team Strategy ────────────────────────────────────
    if any(k in title_lower for k in ("staff", "principal", "lead", "senior")):
        peer_titles = '("Staff Technical Program Manager" OR "Principal TPM" OR "Lead Technical Program Manager" OR "Product Operations")'
        peer_li_keywords = f'{company_short} "Technical Program Manager" OR "Product Operations"'
    else:
        peer_titles = f'("{title}" OR "Technical Program Manager")'
        peer_li_keywords = f'{company_short} "{title}"'

    peer_boolean = f'"{company_full}" AND {peer_titles}'
    if loc_clean:
        peer_boolean += f' AND "{loc_clean}"'

    peer_li_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(peer_li_keywords)}&origin=GLOBAL_SEARCH_HEADER"
    peer_xray_query = f'site:linkedin.com/in/ "{company_full}" {peer_titles}'
    if loc_clean:
        peer_xray_query += f' "{loc_clean}"'
    peer_xray_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(peer_xray_query)}"

    strat_peer = SearchStrategy(
        archetype_id="peer",
        title="👥 Insiders & Peers (Staff / Principal TPMs)",
        target_roles=f"Current {title}s, Staff/Principal TPMs, or Product Ops Leads",
        objective="Gain internal culture insights, team architecture context, and request a warm employee referral.",
        boolean_query=peer_boolean,
        linkedin_url=peer_li_url,
        google_xray_url=peer_xray_url,
        suggested_person_type=PersonType.functional_peer,
        suggested_priority=3,
    )

    # ── 4. Warm Connectors / Alumni Strategy ───────────────────────────────────
    affil = get_candidate_affiliations()
    alumni_tokens = []
    for s in affil.get("schools", []):
        alumni_tokens.append(f'"{s}"')
    for c in affil.get("companies", [])[:3]:  # Top 3: Bell, Amazon, IBM
        alumni_tokens.append(f'"{c}"')

    alumni_or = f"({' OR '.join(alumni_tokens)})"
    alumni_boolean = f'"{company_full}" AND {alumni_or}'

    alumni_li_keywords = f'{company_short} (Rotman OR "University of Toronto" OR Bell OR Amazon OR IBM)'
    alumni_li_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(alumni_li_keywords)}&origin=GLOBAL_SEARCH_HEADER"
    alumni_xray_query = f'site:linkedin.com/in/ "{company_full}" {alumni_or}'
    alumni_xray_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(alumni_xray_query)}"

    strat_alumni = SearchStrategy(
        archetype_id="warm_connector",
        title="🎓 Warm Connectors & Alumni (Rotman, Bell, Amazon, IBM)",
        target_roles="Employees at company with shared background (Rotman / U of T / ex-Amazon / ex-IBM / ex-Bell)",
        objective="Highest response rate (3x cold outreach) due to shared university or past employer affinity.",
        boolean_query=alumni_boolean,
        linkedin_url=alumni_li_url,
        google_xray_url=alumni_xray_url,
        suggested_person_type=PersonType.warm_connector,
        suggested_priority=1,
    )

    return [strat_hm, strat_recruiter, strat_peer, strat_alumni]


def get_discovered_contacts(job: JobRecord) -> list[dict[str, Any]]:
    """
    Return curated, high-relevance discovered stakeholders for a job,
    including title, archetype, and possible relationship to the role.
    """
    company = (job.company or "").strip()
    title = (job.title or "").strip()
    company_clean = _clean_company_name(company)

    # 1. Custom matches for known companies
    contacts: list[dict[str, Any]] = []
    if "lightspeed" in company.lower():
        contacts = [
            {
                "name": "Vera Arkhipova",
                "current_title": "Director",
                "company": company,
                "person_type": PersonType.hiring_manager,
                "relationship_to_job": "Likely Hiring Manager — Director at Lightspeed Commerce overseeing PDLC adoption, operational excellence, and delivery frameworks.",
                "priority": 1,
                "confidence": Confidence.high,
                "source_url": "https://www.linkedin.com/in/vera-arkhipova/",
            },
            {
                "name": "Derek Smockum",
                "current_title": "Senior Talent Acquisition Partner / Recruiter",
                "company": company,
                "person_type": PersonType.recruiter,
                "relationship_to_job": "Confirmed Recruiter — Talent Acquisition Partner at Lightspeed Commerce managing candidate screening and pipeline for the Staff TPM - PDLC role.",
                "priority": 2,
                "confidence": Confidence.high,
                "source_url": "https://www.linkedin.com/in/derek-smockum-449879164/",
            },
            {
                "name": "Anita Nguyen",
                "current_title": "Senior Talent Acquisition Partner",
                "company": company,
                "person_type": PersonType.recruiter,
                "relationship_to_job": "Talent Acquisition Partner — leads full-cycle sourcing and screening for Product & Technology positions.",
                "priority": 2,
                "confidence": Confidence.high,
                "source_url": "https://www.linkedin.com/company/lightspeedhq/people/?keywords=Talent%20Acquisition",
            },
            {
                "name": "Jennifer Kim",
                "current_title": "Manager, Talent Systems Operations",
                "company": company,
                "person_type": PersonType.recruiter,
                "relationship_to_job": "Talent Operations Lead — oversees talent acquisition operations, candidate pipelines, and recruiting systems.",
                "priority": 3,
                "confidence": Confidence.medium,
                "source_url": "https://www.linkedin.com/company/lightspeedhq/people/?keywords=Talent%20Operations",
            },
            {
                "name": "Duncan Wannamaker",
                "current_title": "Head of Product Management (Retail)",
                "company": company,
                "person_type": PersonType.functional_peer,
                "relationship_to_job": "Key Functional Peer & Partner — Head of Product Management at Lightspeed; primary product stakeholder partnering on PDLC adoption and roadmap alignment.",
                "priority": 3,
                "confidence": Confidence.high,
                "source_url": "https://theorg.com/org/lightspeed-commerce",
            },
            {
                "name": "Helen Lee",
                "current_title": "VP of Product Design",
                "company": company,
                "person_type": PersonType.functional_peer,
                "relationship_to_job": "Cross-Functional Partner — VP of Product Design at Lightspeed; core triad stakeholder for the Product Development Lifecycle (PDLC).",
                "priority": 3,
                "confidence": Confidence.high,
                "source_url": "https://theorg.com/org/lightspeed-commerce",
            },
        ]
    else:
        # For companies where real individuals have not yet been identified,
        # return an empty list so the app honestly indicates no one was found,
        # rather than creating fake/placeholder accounts with job titles or company names.
        return []

    # Final safeguard: filter out any entry that is not a real individual human name
    return [c for c in contacts if is_real_person_name(c.get("name", ""))]


def is_real_person_name(name: str) -> bool:
    """Validate that a name represents an actual individual rather than a title or organization."""
    if not name or not isinstance(name, str):
        return False
    clean = name.strip()
    # Check for symbols or numbers common in company names or URLs
    if re.search(r"[\d&@/\\|()\[\]{}*+=_~^$!?;:<>]", clean):
        return False
    parts = [p for p in clean.split() if p]
    if len(parts) < 2 or len(parts) > 5:
        return False
    lower = clean.lower()
    invalid_terms = [
        "head of", "director of", "director /", "vp of", "vice president",
        "lead technical", "senior /", "staff /", "recruiter", "talent acquisition",
        "practice", "manager,", "department", "team", "rosenfelt", "engineering",
        "consultant", "acquisition", "transformation", "anonymous", "unknown",
        "placeholder", "company", "corporation", "services", "technologies",
        "commerce", "holdings", "group", "solutions", "enterprises", "associates",
        "capital", "consulting", "agency", "recruitment", "careers", "hiring",
        "office", "global", "international", "division", "firm", "ventures",
        "management", "systems", "network", "networks", "software", "labs",
        "energy", "power", "logistics", "industries", "industrial", "ltd", "inc", "corp"
    ]
    if any(term in lower for term in invalid_terms):
        return False
    return True


def parse_linkedin_input(raw_input: str, default_company: str = "") -> dict[str, Any]:
    """
    Parse a pasted LinkedIn profile URL or text snippet into structured person fields.
    """
    text = (raw_input or "").strip()
    if not text:
        return {}

    # Check if a company directory URL was pasted instead of an individual profile
    if "linkedin.com/company/" in text:
        return {
            "error": "This is a LinkedIn company page, not an individual person's profile. Please navigate to the 'People' tab on LinkedIn to find individual stakeholders and paste their personal profile URL (linkedin.com/in/...).",
            "is_company_page": True,
        }

    extracted_url: Optional[str] = None
    name = ""
    title = ""
    company = default_company

    # 1. Check for URL inside text
    url_match = re.search(r"https?://(?:[a-zA-Z0-9_-]+\.)?linkedin\.com/in/([a-zA-Z0-9_\-%]+)/?", text)
    if url_match:
        extracted_url = url_match.group(0).rstrip("/")
        slug = url_match.group(1)
        # Infer name from slug by splitting hyphenated words
        # Only drop trailing segment if it contains digits (like random hash 'john-doe-4819a3b')
        parts = [p for p in slug.split("-") if p]
        if len(parts) > 1 and re.search(r"\d", parts[-1]):
            parts = parts[:-1]
        slug_name = " ".join(p.capitalize() for p in parts if not p.isdigit())
        if slug_name and is_real_person_name(slug_name):
            name = slug_name

    # 2. Parse text lines
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    non_url_lines = [l for l in lines if not l.startswith("http")]

    if non_url_lines:
        first_line = non_url_lines[0]
        parts = re.split(r"[|·•\-\–\—]", first_line)
        if len(parts) >= 2:
            name_candidate = parts[0].strip()
            name_candidate = re.sub(r"\b(?:1st|2nd|3rd|\d+th)\b", "", name_candidate).strip()
            if name_candidate and len(name_candidate.split()) <= 4:
                name = name_candidate

            title_candidate = parts[1].strip()
            title_candidate = re.sub(r"\b(?:1st|2nd|3rd|\d+th)\b", "", title_candidate).strip()
            if title_candidate:
                title = title_candidate

            if len(parts) >= 3 and not title:
                title = parts[2].strip()
        else:
            if len(first_line.split()) <= 4 and not any(k in first_line.lower() for k in ("director", "manager", "recruiter", "vp", "engineer")):
                name = first_line
            if len(non_url_lines) >= 2:
                title = non_url_lines[1]

    name = re.sub(r"\(.*?\)", "", name).strip()
    name = re.sub(r"^[·•\-\s]+|[·•\-\s]+$", "", name).strip()

    if " at " in title:
        t_part, c_part = title.split(" at ", 1)
        title = t_part.strip()
        parsed_comp = c_part.split("|")[0].split("·")[0].strip()
        if parsed_comp and not company:
            company = parsed_comp
    elif " @ " in title:
        t_part, c_part = title.split(" @ ", 1)
        title = t_part.strip()
        parsed_comp = c_part.split("|")[0].split("·")[0].strip()
        if parsed_comp and not company:
            company = parsed_comp

    # 3. Classify PersonType and Priority based on Title
    title_lower = title.lower()
    if any(k in title_lower for k in ("recruiter", "talent acquisition", "sourcer", "talent partner")):
        person_type = PersonType.recruiter
        priority = 2
        relationship = f"Technical Recruiter / Talent Acquisition at {company}"
    elif any(k in title_lower for k in ("vp", "vice president", "director", "head of", "senior director", "chief")):
        person_type = PersonType.hiring_manager
        priority = 1
        relationship = f"Potential Hiring Manager / Leadership at {company}"
    elif any(k in title_lower for k in ("staff", "principal", "senior", "lead")) and any(k in title_lower for k in ("tpm", "program manager", "product ops")):
        person_type = PersonType.functional_peer
        priority = 3
        relationship = f"Functional Peer / Team Member at {company}"
    elif any(k in title_lower for k in ("product", "engineering", "architecture")):
        person_type = PersonType.functional_peer
        priority = 3
        relationship = f"Cross-functional Colleague at {company}"
    else:
        person_type = PersonType.hiring_manager
        priority = 2
        relationship = f"Key Contact at {company}"

    return {
        "name": name or "LinkedIn Contact",
        "current_title": title or "Professional",
        "company": company,
        "source_url": extracted_url,
        "person_type": person_type,
        "outreach_priority": priority,
        "relationship_to_job": relationship,
        "confidence": Confidence.high if extracted_url else Confidence.medium,
    }
