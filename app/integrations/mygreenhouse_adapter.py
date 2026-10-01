"""
MyGreenhouse adapter.
Reads candidate-portal-visible applications and statuses.
Never stores credentials, MFA codes, or bypasses authentication controls.
"""
from __future__ import annotations

from typing import Optional

from app.integrations.portal_base import JobPortalAdapter, PortalJob, PortalStatus


class MyGreenhouseAdapter(JobPortalAdapter):
    """
    MyGreenhouse candidate portal adapter.
    MVP mode: stub with explicit session-status reporting.
    Full implementation requires user-controlled authenticated browser capability.
    """

    @property
    def portal_name(self) -> str:
        return "MyGreenhouse"

    def status(self) -> PortalStatus:
        return PortalStatus(
            provider="mygreenhouse",
            authenticated=False,
            public_mode=False,
            message=(
                "MyGreenhouse adapter not configured. "
                "Requires user-interactive session — no credential storage or automation."
            ),
            capabilities=[],
        )

    def search(
        self,
        query: str,
        location: str = "Canada",
        max_results: int = 25,
    ) -> list[PortalJob]:
        """MyGreenhouse does not support public job search. Returns empty list."""
        return []

    def fetch_description(self, job: PortalJob) -> Optional[str]:
        return None

    def get_application_status(self, external_app_id: str) -> Optional[dict]:
        """
        Retrieve application status from MyGreenhouse portal.
        Returns None when session is not configured.
        """
        return None

    def list_applications(self) -> list[dict]:
        """
        Return portal-visible applications when session is configured.
        Stub — returns empty list until authenticated session is available.
        """
        return []


def session_status() -> dict:
    """Legacy shim for backward compatibility."""
    return {"provider": "mygreenhouse", "state": "not_configured"}
