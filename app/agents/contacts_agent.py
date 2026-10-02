"""
Contacts Agent — finds and verifies hiring contacts for a queued job.

Strategy (no login required):
  1. Use existing linkedin_finder.build_search_strategies() for search URLs
  2. Check the ATS job posting page for recruiter/coordinator mention
  3. Query the company's Ashby/Greenhouse/Lever board API for open roles that
     reveal a recruiter email or coordinator name in the job metadata
  4. Return verified + suggested contacts for human review in the Coordinator UI

The agent does NOT log into LinkedIn. It generates direct search URLs the user
can open manually, and it scrapes publicly accessible ATS metadata.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from app.models import Confidence, JobRecord, PersonTarget, PersonType
from app.services.linkedin_finder import (
    SearchStrategy,
    _clean_company_name,
    build_search_strategies,
    get_discovered_contacts,
    is_real_person_name,
)
from app.integrations.ats_boards import USER_AGENT

log = logging.getLogger("contacts_agent")

ROOT = Path(__file__).resolve().parent.parent.parent
CONTACTS_DIR = ROOT / "data" / "contacts"


# ─────────────────────────────────────────────────────────────────────────────
# ATS Metadata Scrapers (public API — no login)
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_ashby_posting(posting_id: str, slug: str) -> dict:
    """Fetch a single Ashby job posting for recruiter metadata."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(url)
            r.raise_for_status()
            jobs = r.json().get("jobs", [])
            for job in jobs:
                if job.get("id") == posting_id:
                    return job
    except Exception as exc:
        log.debug("Ashby metadata fetch failed: %s", exc)
    return {}


def _scrape_greenhouse_posting(job_id: str, board_token: str) -> dict:
    """Fetch Greenhouse job JSON (public API)."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}?questions=true"
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        log.debug("Greenhouse metadata fetch failed: %s", exc)
    return {}


def _extract_ids_from_url(url: str) -> dict:
    """Parse ATS-specific IDs and slugs from a job posting URL."""
    result = {"ats": "unknown", "job_id": "", "board_slug": ""}
    url = url or ""

    # Ashby: https://jobs.ashbyhq.com/{slug}/{posting_id}
    m = re.match(r"https://jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if m:
        result.update({"ats": "ashby", "board_slug": m.group(1), "job_id": m.group(2)})
        return result

    # Greenhouse: https://boards.greenhouse.io/{token}/jobs/{id}
    m = re.match(r"https://(?:boards|job-boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if m:
        result.update({"ats": "greenhouse", "board_slug": m.group(1), "job_id": m.group(2)})
        return result

    # Lever: https://jobs.lever.co/{company}/{id}
    m = re.match(r"https://jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    if m:
        result.update({"ats": "lever", "board_slug": m.group(1), "job_id": m.group(2)})
        return result

    return result


def _contacts_from_ats_metadata(url: str, company: str) -> list[dict]:
    """
    Pull any recruiter/coordinator info embedded in public ATS metadata.
    Returns a list of partial contact dicts (may lack name, needs verification).
    """
    ids = _extract_ids_from_url(url)
    contacts = []

    if ids["ats"] == "ashby" and ids["job_id"] and ids["board_slug"]:
        posting = _scrape_ashby_posting(ids["job_id"], ids["board_slug"])
        # Ashby sometimes exposes a coordinator field in job metadata
        coordinator = posting.get("hiringTeam", {})
        if coordinator:
            for role, person in coordinator.items():
                if isinstance(person, dict) and person.get("name"):
                    contacts.append({
                        "name": person["name"],
                        "current_title": person.get("title", role.replace("_", " ").title()),
                        "company": company,
                        "person_type": PersonType.recruiter
                            if "recruit" in role.lower() or "coord" in role.lower()
                            else PersonType.hiring_manager,
                        "confidence": Confidence.high,
                        "source": "ats_metadata",
                        "source_url": url,
                        "relationship_to_job": f"Listed in Ashby job posting metadata as {role}",
                        "verified": True,
                    })

    elif ids["ats"] == "greenhouse" and ids["job_id"] and ids["board_slug"]:
        data = _scrape_greenhouse_posting(ids["job_id"], ids["board_slug"])
        # Greenhouse sometimes exposes office/department contacts
        dept = data.get("departments", [{}])
        if isinstance(dept, list) and dept:
            log.debug("Greenhouse dept data: %s", dept)

    return [c for c in contacts if is_real_person_name(c.get("name", ""))]


# ─────────────────────────────────────────────────────────────────────────────
# Main Contacts Agent
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ContactVerificationResult:
    """Result of contact verification for one job."""
    job_id: str
    company: str
    title: str
    url: str

    # Contacts confirmed from ATS metadata (highest confidence)
    verified_contacts: list[dict] = field(default_factory=list)

    # Curated hardcoded contacts for known companies
    curated_contacts: list[dict] = field(default_factory=list)

    # Search strategies for user to find contacts manually
    search_strategies: list[SearchStrategy] = field(default_factory=list)

    # Direct search URLs the user can open
    quick_links: list[dict] = field(default_factory=list)

    def all_contacts(self) -> list[dict]:
        """All confirmed contacts (verified + curated), deduped by name."""
        seen, out = set(), []
        for c in self.verified_contacts + self.curated_contacts:
            key = (c.get("name", "")).lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(c)
        return out

    def has_contacts(self) -> bool:
        return bool(self.verified_contacts or self.curated_contacts)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "company": self.company,
            "title": self.title,
            "url": self.url,
            "verified_contacts": self.verified_contacts,
            "curated_contacts": self.curated_contacts,
            "quick_links": self.quick_links,
            "strategies_count": len(self.search_strategies),
        }


class ContactsAgent:
    """
    Verifies and discovers hiring contacts for a queued job.

    Pipeline:
      1. Check ATS metadata (Ashby/Greenhouse) for embedded recruiter data
      2. Check curated hardcoded contacts (linkedin_finder.get_discovered_contacts)
      3. Generate targeted search strategies (LinkedIn + Google X-Ray URLs)
      4. Return ContactVerificationResult for human review in UI
    """

    def run(self, job_id: str, company: str, title: str, url: str) -> ContactVerificationResult:
        """Main entry point — returns verification result for display in Coordinator UI."""
        log.info("Running contacts verification for %s — %s", company, title)

        result = ContactVerificationResult(
            job_id=job_id,
            company=company,
            title=title,
            url=url,
        )

        # Step 1: ATS metadata scrape
        if url:
            try:
                ats_contacts = _contacts_from_ats_metadata(url, company)
                result.verified_contacts = ats_contacts
                if ats_contacts:
                    log.info("Found %d contacts from ATS metadata", len(ats_contacts))
            except Exception as exc:
                log.warning("ATS metadata scrape failed: %s", exc)

        # Step 2: Curated contacts for known companies
        dummy_job = JobRecord(company=company, title=title, description="")
        try:
            curated = get_discovered_contacts(dummy_job)
            result.curated_contacts = [self._to_contact_dict(c, company) for c in curated]
        except Exception as exc:
            log.debug("Curated contacts lookup failed: %s", exc)

        # Step 3: Build search strategies
        try:
            result.search_strategies = build_search_strategies(dummy_job)
            result.quick_links = self._build_quick_links(company, title, url)
        except Exception as exc:
            log.warning("Search strategy build failed: %s", exc)

        # Step 4: Persist result to disk
        self._save(result)
        return result

    def load(self, job_id: str) -> Optional[ContactVerificationResult]:
        """Load a previously saved verification result."""
        path = self._path(job_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                r = ContactVerificationResult(
                    job_id=data["job_id"],
                    company=data["company"],
                    title=data["title"],
                    url=data["url"],
                    verified_contacts=data.get("verified_contacts", []),
                    curated_contacts=data.get("curated_contacts", []),
                    quick_links=data.get("quick_links", []),
                )
                return r
            except Exception:
                pass
        return None

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def _to_contact_dict(self, p: PersonTarget, company: str) -> dict:
        return {
            "name": p.name,
            "current_title": p.current_title or "",
            "company": p.company or company,
            "person_type": p.person_type.value if hasattr(p.person_type, "value") else str(p.person_type),
            "confidence": p.confidence.value if hasattr(p.confidence, "value") else str(p.confidence),
            "relationship_to_job": p.relationship_to_job or "",
            "source_url": p.source_url or "",
            "verified": True,
            "source": "curated",
        }

    def _build_quick_links(self, company: str, title: str, url: str) -> list[dict]:
        """Generate immediately-clickable search URLs."""
        import urllib.parse
        clean = _clean_company_name(company)

        links = []

        # LinkedIn company people search
        li_company_q = urllib.parse.quote_plus(f"{clean}")
        links.append({
            "label": f"🔵 {company} People on LinkedIn",
            "url": f"https://www.linkedin.com/company/{li_company_q.lower().replace('+', '-')}/people/",
            "purpose": "Browse all employees — filter by Recruiting or Engineering leadership",
        })

        # LinkedIn recruiter search
        li_recruiter_q = urllib.parse.quote_plus(f"{clean} recruiter talent acquisition")
        links.append({
            "label": "🔎 Find Recruiter on LinkedIn",
            "url": f"https://www.linkedin.com/search/results/people/?keywords={li_recruiter_q}",
            "purpose": "Find the recruiter managing this role",
        })

        # LinkedIn hiring manager search
        role_kw = "Technical Program" if "program manager" in title.lower() else title.split()[0]
        li_hm_q = urllib.parse.quote_plus(f"{clean} {role_kw} Director VP Head")
        links.append({
            "label": "🔎 Find Hiring Manager on LinkedIn",
            "url": f"https://www.linkedin.com/search/results/people/?keywords={li_hm_q}",
            "purpose": "Find the Director/VP who likely owns this team",
        })

        # Google X-Ray for recruiter
        gx_q = urllib.parse.quote_plus(
            f'site:linkedin.com/in "{clean}" ("recruiter" OR "talent acquisition") '
            f'("{role_kw}" OR "engineering" OR "technical")'
        )
        links.append({
            "label": "🔍 Google X-Ray: Recruiter",
            "url": f"https://www.google.com/search?q={gx_q}",
            "purpose": "Google X-Ray search bypasses LinkedIn login wall",
        })

        # The Org — company org chart
        theorg_q = urllib.parse.quote_plus(clean.lower())
        links.append({
            "label": f"🏢 {company} Org Chart (The Org)",
            "url": f"https://theorg.com/search?q={theorg_q}",
            "purpose": "Public org chart — often reveals direct manager names",
        })

        return links

    def _path(self, job_id: str) -> Path:
        safe = re.sub(r"[^\w]", "_", job_id)[:80]
        return CONTACTS_DIR / f"{safe}.json"

    def _save(self, result: ContactVerificationResult) -> None:
        CONTACTS_DIR.mkdir(parents=True, exist_ok=True)
        self._path(result.job_id).write_text(
            json.dumps(result.to_dict(), indent=2, default=str, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
