"""
Base interface for all job portal adapters.
Each portal adapter must implement this interface.
Public-mode (no authentication) must always work.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PortalJob:
    """Normalized job posting returned by any portal adapter."""
    portal: str
    external_id: Optional[str]
    title: str
    company: str
    location: Optional[str]
    country: Optional[str]
    work_model: Optional[str]            # remote / hybrid / on-site
    url: str
    source_type: str                     # "official_career" | "indeed" | "linkedin" | ...
    description: Optional[str]
    posted_date: Optional[str]           # ISO 8601 string or None
    is_open: Optional[bool] = None       # None = unknown
    raw: dict = field(default_factory=dict)


@dataclass
class PortalStatus:
    provider: str
    authenticated: bool
    public_mode: bool
    message: str
    capabilities: list[str] = field(default_factory=list)


class JobPortalAdapter(ABC):
    """Abstract base class all portal adapters must implement."""

    @property
    @abstractmethod
    def portal_name(self) -> str:
        """Human-readable portal name, e.g. 'Indeed', 'LinkedIn'."""
        ...

    @abstractmethod
    def status(self) -> PortalStatus:
        """Return current session/authentication status."""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        location: str = "Canada",
        max_results: int = 25,
    ) -> list[PortalJob]:
        """
        Search for jobs and return normalized PortalJob objects.
        Must work in public mode. Raises NotImplementedError if portal
        requires authentication not yet configured.
        """
        ...

    @abstractmethod
    def fetch_description(self, job: PortalJob) -> Optional[str]:
        """
        Fetch the full job description text for a listing.
        Returns None if unavailable.
        """
        ...

    def to_job_record_dict(self, portal_job: PortalJob) -> dict:
        """Convert a PortalJob to a dict suitable for JobRecord construction."""
        return {
            "company":     portal_job.company,
            "title":       portal_job.title,
            "job_id":      portal_job.external_id,
            "official_url": portal_job.url,
            "source_url":  portal_job.url,
            "source_type": portal_job.source_type,
            "location":    portal_job.location,
            "country":     portal_job.country,
            "work_model":  portal_job.work_model,
            "description": portal_job.description or "",
            "status":      "OPEN" if portal_job.is_open else "UNKNOWN",
        }
