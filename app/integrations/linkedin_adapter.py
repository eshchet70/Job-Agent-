"""
LinkedIn adapter.
Public mode: search URL builder only (LinkedIn blocks unauthenticated scraping).
Authenticated mode: requires user-interactive session; never stores passwords or MFA.

MVP policy (from authenticated-account-integration SKILL.md):
  - Use interactive user authorization only.
  - Never request/store passwords or MFA codes.
  - Never bypass CAPTCHA, MFA, rate limits, or access controls.
  - Public/manual mode must remain functional at all times.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from app.integrations.portal_base import JobPortalAdapter, PortalJob, PortalStatus


class LinkedInAdapter(JobPortalAdapter):
    """
    LinkedIn adapter.
    Public mode: generates search URLs for manual browser use.
    Authenticated mode: stub — requires user-controlled session (not implemented in MVP).
    """

    @property
    def portal_name(self) -> str:
        return "LinkedIn"

    def status(self) -> PortalStatus:
        return PortalStatus(
            provider="linkedin",
            authenticated=False,
            public_mode=True,
            message=(
                "LinkedIn public mode — generates search URLs for manual use. "
                "Authenticated enrichment requires user-interactive session (not configured)."
            ),
            capabilities=["search_url_builder"],
        )

    def search(
        self,
        query: str,
        location: str = "Canada",
        max_results: int = 25,
    ) -> list[PortalJob]:
        """
        LinkedIn blocks unauthenticated programmatic access.
        Returns an empty list; use build_search_url() to generate a manual URL.
        """
        return []

    def fetch_description(self, job: PortalJob) -> Optional[str]:
        return None

    def build_search_url(
        self,
        query: str,
        location: str = "Canada",
        experience_level: str = "4",   # 4=Senior, 5=Director+, 6=Executive
    ) -> str:
        """
        Build a LinkedIn Jobs search URL for manual browser use.
        Experience levels: 1=Intern, 2=Entry, 3=Associate, 4=Senior, 5=Director, 6=Executive
        """
        params = {
            "keywords": query,
            "location": location,
            "f_E": experience_level,
            "sortBy": "DD",     # date descending
        }
        return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"


def session_status() -> dict:
    """Legacy shim for backward compatibility."""
    return {"provider": "linkedin", "state": "not_configured"}
