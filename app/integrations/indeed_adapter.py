"""
Indeed adapter — public search via Indeed's unofficial RSS feed.
No authentication required. No credential storage.
Rate-limit: respect robots.txt; max 25 results per query.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urlencode, urljoin

import httpx

from app.config import settings
from app.integrations.portal_base import JobPortalAdapter, PortalJob, PortalStatus

_BASE_RSS = "https://www.indeed.com/rss"
_BASE_CA = "https://ca.indeed.com/jobs"

# Work model detection patterns
_REMOTE_PATTERNS = [r"\bremote\b", r"\bwork from home\b", r"\bwfh\b"]
_HYBRID_PATTERNS = [r"\bhybrid\b", r"\bflexible work\b"]


class IndeedAdapter(JobPortalAdapter):
    """
    Public Indeed adapter using the RSS feed.
    Authentication scope: none (public RSS only).
    Limitations: descriptions are truncated in RSS; full-text requires additional fetch.
    """

    @property
    def portal_name(self) -> str:
        return "Indeed"

    def status(self) -> PortalStatus:
        return PortalStatus(
            provider="indeed",
            authenticated=False,
            public_mode=True,
            message="Public RSS mode — no authentication required.",
            capabilities=["search", "rss_description"],
        )

    def search(
        self,
        query: str,
        location: str = "Canada",
        max_results: int = 25,
    ) -> list[PortalJob]:
        """Search Indeed via RSS feed and return normalized PortalJob objects."""
        params = {
            "q": query,
            "l": location,
            "limit": min(max_results, 25),
            "sort": "date",
        }
        url = f"{_BASE_RSS}?{urlencode(params)}"

        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True,
                             headers={"User-Agent": "JobSearchAgent/1.0 (educational use)"})
            resp.raise_for_status()
            return self._parse_rss(resp.text, max_results)
        except httpx.HTTPError as exc:
            # Graceful degradation — return empty list, not crash
            return []

    def fetch_description(self, job: PortalJob) -> Optional[str]:
        """Return the description already extracted from RSS (truncated)."""
        return job.description

    # ------------------------------------------------------------------

    def _parse_rss(self, xml_text: str, max_results: int) -> list[PortalJob]:
        results: list[PortalJob] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return results

        ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
        channel = root.find("channel")
        if channel is None:
            return results

        for item in channel.findall("item")[:max_results]:
            title = _text(item, "title")
            link = _text(item, "link")
            desc = _text(item, "description") or ""
            pub_date = _text(item, "pubDate")
            company = self._extract_company(desc, title)
            location_str = self._extract_location(desc)
            work_model = self._detect_work_model(title + " " + desc)
            job_id = self._extract_job_id(link)

            results.append(PortalJob(
                portal="Indeed",
                external_id=job_id,
                title=title,
                company=company,
                location=location_str,
                country=_guess_country(location_str),
                work_model=work_model,
                url=link,
                source_type="indeed",
                description=_strip_html(desc),
                posted_date=pub_date,
                is_open=True,
                raw={"rss_description": desc},
            ))
        return results

    @staticmethod
    def _extract_company(desc: str, title: str) -> str:
        # Indeed RSS often includes company in the description
        m = re.search(r"<b>([^<]{2,80})</b>", desc)
        if m:
            return m.group(1).strip()
        return "Unknown"

    @staticmethod
    def _extract_location(desc: str) -> Optional[str]:
        m = re.search(r"-\s+([A-Za-z ,]{3,60})\s*<", desc)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _detect_work_model(text: str) -> Optional[str]:
        lower = text.lower()
        if any(re.search(p, lower) for p in _REMOTE_PATTERNS):
            return "remote"
        if any(re.search(p, lower) for p in _HYBRID_PATTERNS):
            return "hybrid"
        return "on-site"

    @staticmethod
    def _extract_job_id(url: str) -> Optional[str]:
        m = re.search(r"jk=([a-f0-9]+)", url)
        return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()


def _guess_country(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    loc_lower = location.lower()
    if any(prov in loc_lower for prov in [
        "ontario", "british columbia", "alberta", "quebec", "toronto",
        "vancouver", "montreal", "calgary", "ottawa", ", on", ", bc", ", ab", "canada"
    ]):
        return "Canada"
    if any(st in loc_lower for st in [
        "new york", "california", "texas", "washington", "seattle",
        ", ny", ", ca", ", tx", ", wa", "united states", "usa"
    ]):
        return "United States"
    return None
