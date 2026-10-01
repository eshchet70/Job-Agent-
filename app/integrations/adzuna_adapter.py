"""
Adzuna adapter — official job-aggregator API (free developer key).

Covers Canadian job boards and employer sites far beyond the company
watchlist, including banks, telcos and consultancies on Workday/Taleo that
have no public JSON board.

Get keys at https://developer.adzuna.com/ and set ADZUNA_APP_ID and
ADZUNA_APP_KEY (GitHub secrets for the daily workflow).

Limitation: Adzuna returns a ~500-character description snippet, not the
full JD. Jobs from this source are scored on title + snippet and flagged
`partial_description` so the dashboard can say so.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import httpx

from app.integrations.ats_boards import USER_AGENT, detect_work_model, guess_country, html_to_text
from app.integrations.portal_base import JobPortalAdapter, PortalJob, PortalStatus

API_BASE = "https://api.adzuna.com/v1/api/jobs"


class AdzunaAdapter(JobPortalAdapter):

    def __init__(self, app_id: Optional[str] = None, app_key: Optional[str] = None,
                 country: str = "ca", client: Optional[httpx.Client] = None):
        self.app_id = app_id if app_id is not None else os.getenv("ADZUNA_APP_ID", "")
        self.app_key = app_key if app_key is not None else os.getenv("ADZUNA_APP_KEY", "")
        self.country = country
        self._client = client

    @property
    def portal_name(self) -> str:
        return "Adzuna"

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_key)

    def status(self) -> PortalStatus:
        return PortalStatus(
            provider="adzuna",
            authenticated=self.configured,
            public_mode=False,
            message=("Adzuna API configured." if self.configured
                     else "Set ADZUNA_APP_ID and ADZUNA_APP_KEY to enable aggregator search."),
            capabilities=["search"] if self.configured else [],
        )

    def search(self, query: str, location: str = "Canada", max_results: int = 50,
               max_days_old: int = 3) -> list[PortalJob]:
        if not self.configured:
            return []
        results: list[PortalJob] = []
        page = 1
        per_page = min(50, max_results)
        client = self._client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
        try:
            while len(results) < max_results:
                params = {
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "what_phrase": query,
                    "results_per_page": per_page,
                    "max_days_old": max_days_old,
                    "sort_by": "date",
                    "content-type": "application/json",
                }
                if location and location.lower() != "canada":
                    params["where"] = location
                resp = client.get(f"{API_BASE}/{self.country}/search/{page}", params=params)
                resp.raise_for_status()
                batch = resp.json().get("results", [])
                results.extend(self._normalize(r) for r in batch)
                if len(batch) < per_page:
                    break
                page += 1
        except httpx.HTTPError:
            pass  # degrade gracefully; the run report shows the source returned nothing
        finally:
            if self._client is None:
                client.close()
        return results[:max_results]

    def fetch_description(self, job: PortalJob) -> Optional[str]:
        return job.description

    @staticmethod
    def _normalize(r: dict) -> PortalJob:
        title = html_to_text(r.get("title"))
        loc = (r.get("location") or {}).get("display_name")
        desc = html_to_text(r.get("description"))
        return PortalJob(
            portal="Adzuna",
            external_id=str(r.get("id")),
            title=re.sub(r"\s+", " ", title).strip(),
            company=((r.get("company") or {}).get("display_name") or "Unknown").strip(),
            location=loc,
            country=guess_country(loc) or "Canada",
            work_model=detect_work_model(title, desc, loc),
            url=r.get("redirect_url") or "",
            source_type="adzuna",
            description=desc,
            posted_date=(r.get("created") or "")[:10] or None,
            is_open=True,
            raw={"partial_description": True,
                 "salary_min": r.get("salary_min"), "salary_max": r.get("salary_max")},
        )
