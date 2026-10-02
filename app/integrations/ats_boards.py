"""
Public applicant-tracking-system (ATS) job boards.

Most tech employers publish their openings through one of a few ATS vendors,
each of which exposes an unauthenticated, read-only JSON API intended for
embedding job lists on career sites:

  Greenhouse  https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  Lever       https://api.lever.co/v0/postings/{company}?mode=json
  Ashby       https://api.ashbyhq.com/posting-api/job-board/{org}

No credentials, no scraping, no CAPTCHA concerns. Each fetcher returns a
list of normalized PortalJob objects and raises BoardNotFound when the slug
does not exist (so the watchlist health check can report it).
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Callable, Optional

import httpx

from app.integrations.portal_base import PortalJob

USER_AGENT = "JobSearchAgent/1.0 (personal job search; contact via repo owner)"
TIMEOUT = 30


class BoardNotFound(Exception):
    """The board slug does not exist on this ATS."""


class BoardError(Exception):
    """Transient or unexpected failure fetching a board."""


def _get_json(url: str, client: Optional[httpx.Client] = None, params: Optional[dict] = None):
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                                    follow_redirects=True)
    try:
        resp = client.get(url, params=params)
        if resp.status_code == 404:
            raise BoardNotFound(url)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise BoardError(f"{url}: {exc}") from exc
    finally:
        if own:
            client.close()


def html_to_text(raw: Optional[str]) -> str:
    """Convert (possibly entity-escaped) HTML into readable plain text."""
    if not raw:
        return ""
    text = html.unescape(raw)          # Greenhouse double-escapes content
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def detect_work_model(*parts: Optional[str]) -> Optional[str]:
    blob = " ".join(p for p in parts if p).lower()
    if re.search(r"\bremote\b|work from home", blob):
        return "remote"
    if "hybrid" in blob:
        return "hybrid"
    if re.search(r"on[- ]site|in[- ]office", blob):
        return "on-site"
    return None


_CANADA_HINTS = ("canada", "toronto", "ontario", "vancouver", "montreal", "montréal", "ottawa",
                 "calgary", "waterloo", "kitchener", "mississauga", "british columbia", "quebec",
                 "québec", "alberta", ", on", ", bc", ", ab", ", qc")
_US_HINTS = ("united states", "new york", "san francisco", "seattle", "california",
             "texas", ", ny", ", ca", ", wa", ", tx", ", ma", ", il", "chicago", "boston", "austin")
# "US" / "USA" / "U.S." as a standalone token ("Remote - US: Select locations").
_US_TOKEN = re.compile(r"(?<![A-Za-z])(?:USA?|U\.S\.A?\.?)(?![A-Za-z])")
# Places that are clearly neither Canada nor the US. Not exhaustive: anything
# unrecognised stays None and the location filter decides what to do with it.
_OTHER_HINTS = ("united kingdom", "london", "uk", "ireland", "dublin", "germany", "berlin", "munich",
                "france", "paris", "netherlands", "amsterdam", "spain", "poland", "sweden",
                "switzerland", "emea", "europe", "india", "bangalore", "bengaluru", "hyderabad",
                "singapore", "japan", "tokyo", "korea", "seoul", "china", "australia", "sydney",
                "apac", "asia", "israel", "tel aviv", "brazil", "mexico", "latam", "dubai", "uae")


def _has_word(text: str, needle: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", text) is not None


def guess_country(location: Optional[str]) -> Optional[str]:
    """
    Country implied by a posting's own location text.

    A posting that lists several locations counts as Canada if any of them is
    Canadian. Returns "Canada", "United States", "Other", or None when the
    text gives no usable signal (e.g. just "Remote").
    """
    if not location:
        return None
    lower = location.lower()
    if any(h in lower for h in _CANADA_HINTS):
        return "Canada"
    if any(h in lower for h in _US_HINTS) or _US_TOKEN.search(location):
        return "United States"
    if any(_has_word(lower, h) for h in _OTHER_HINTS):
        return "Other"
    return None


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):  # Lever: epoch millis
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
    return str(ts)[:10]


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

def fetch_greenhouse(slug: str, company: str, client: Optional[httpx.Client] = None) -> list[PortalJob]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                     client, params={"content": "true"})
    jobs = []
    for j in data.get("jobs", []):
        # Use the posting's own location. The board-level "offices" list covers
        # every office the company has, so it is only a fallback when the
        # posting states no location at all.
        location = (j.get("location") or {}).get("name")
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) if o.get("name"))
        loc = location or offices or None
        desc = html_to_text(j.get("content"))
        jobs.append(PortalJob(
            portal="Greenhouse",
            external_id=str(j.get("id")),
            title=(j.get("title") or "").strip(),
            company=company,
            location=loc,
            country=guess_country(loc),
            work_model=detect_work_model(loc, j.get("title")),
            url=j.get("absolute_url") or "",
            source_type="official_career",
            description=desc,
            posted_date=_iso(j.get("first_published") or j.get("updated_at")),
            is_open=True,
            raw={"departments": [d.get("name") for d in j.get("departments", [])]},
        ))
    return jobs


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

def fetch_lever(slug: str, company: str, client: Optional[httpx.Client] = None) -> list[PortalJob]:
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}", client, params={"mode": "json"})
    if isinstance(data, dict) and data.get("ok") is False:
        raise BoardNotFound(slug)
    jobs = []
    for j in data or []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or []) or None
        sections = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            sections.append(lst.get("text", ""))
            sections.append(html_to_text(lst.get("content")))
        sections.append(j.get("additionalPlain") or "")
        jobs.append(PortalJob(
            portal="Lever",
            external_id=j.get("id"),
            title=(j.get("text") or "").strip(),
            company=company,
            location=loc,
            country=guess_country(loc) or (j.get("country") == "CA" and "Canada") or None,
            work_model=(j.get("workplaceType") or "").replace("onsite", "on-site") or detect_work_model(loc),
            url=j.get("hostedUrl") or "",
            source_type="official_career",
            description="\n\n".join(s for s in sections if s).strip(),
            posted_date=_iso(j.get("createdAt")),
            is_open=True,
            raw={"team": cats.get("team"), "commitment": cats.get("commitment")},
        ))
    return jobs


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------

def fetch_ashby(slug: str, company: str, client: Optional[httpx.Client] = None) -> list[PortalJob]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", client,
                     params={"includeCompensation": "true"})
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""]
        for sec in j.get("secondaryLocations") or []:
            locs.append(sec.get("location", ""))
        loc = "; ".join(l for l in locs if l) or None
        wm = (j.get("workplaceType") or "").lower()
        work_model = {"remote": "remote", "hybrid": "hybrid", "onsite": "on-site"}.get(wm) \
            or ("remote" if j.get("isRemote") else detect_work_model(loc))
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        jobs.append(PortalJob(
            portal="Ashby",
            external_id=j.get("id"),
            title=(j.get("title") or "").strip(),
            company=company,
            location=loc,
            country=guess_country(loc),
            work_model=work_model,
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            source_type="official_career",
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            posted_date=_iso(j.get("publishedAt")),
            is_open=True,
            raw={"department": j.get("department"), "compensation": comp},
        ))
    return jobs


FETCHERS: dict[str, Callable[..., list[PortalJob]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def fetch_board(ats: str, slug: str, company: str, client: Optional[httpx.Client] = None) -> list[PortalJob]:
    try:
        fetcher = FETCHERS[ats.lower()]
    except KeyError:
        raise ValueError(f"Unsupported ATS '{ats}'. Supported: {sorted(FETCHERS)}")
    return fetcher(slug, company, client)
