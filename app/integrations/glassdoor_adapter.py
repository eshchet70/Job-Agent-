"""
Glassdoor adapter — public job search URL builder.
Glassdoor blocks unauthenticated scraping; generates manual URLs in public mode.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from app.integrations.portal_base import JobPortalAdapter, PortalJob, PortalStatus


class GlassdoorAdapter(JobPortalAdapter):

    @property
    def portal_name(self) -> str:
        return "Glassdoor"

    def status(self) -> PortalStatus:
        return PortalStatus(
            provider="glassdoor",
            authenticated=False,
            public_mode=True,
            message="Glassdoor public mode — generates search URLs for manual browser use.",
            capabilities=["search_url_builder"],
        )

    def search(
        self,
        query: str,
        location: str = "Canada",
        max_results: int = 25,
    ) -> list[PortalJob]:
        """Glassdoor blocks unauthenticated scraping. Returns empty list."""
        return []

    def fetch_description(self, job: PortalJob) -> Optional[str]:
        return None

    def build_search_url(self, query: str, location: str = "Canada") -> str:
        params = {
            "sc.keyword": query,
            "locT": "N",
            "locId": "3",        # Canada national
        }
        return f"https://www.glassdoor.ca/Job/jobs.htm?{urlencode(params)}"
