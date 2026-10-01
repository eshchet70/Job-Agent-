"""
Cheap pre-filters applied before the scoring pipeline.

Boards return every opening a company has (often hundreds); only titles that
look like Elena's target families, in acceptable locations, at allowed
companies are worth scoring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.integrations.portal_base import PortalJob

# Titles that carry program/portfolio scope even without a seniority word
# (big-tech TPM titles are often unlevelled, e.g. "Technical Program Manager, Payments").
_SCOPE_WITHOUT_LEVEL = ("technical program manager", "portfolio", "program director",
                        "head of", "director")


def _has_any(text: str, needles: list[str]) -> Optional[str]:
    for n in needles:
        if re.search(r"(?<![a-z])" + re.escape(n.lower()) + r"(?![a-z])", text):
            return n
    return None


@dataclass
class FilterResult:
    keep: bool
    reason: str = ""
    flags: tuple[str, ...] = ()


def title_filter(title: str, cfg: dict) -> FilterResult:
    t = (title or "").lower()
    tf = cfg["title_filters"]
    bad = _has_any(t, tf.get("exclude_any", []))
    if bad:
        return FilterResult(False, f"title excluded ({bad})")
    if not _has_any(t, tf.get("include_any", [])):
        return FilterResult(False, "title not a target family")
    if not (_has_any(t, tf.get("seniority_any", [])) or any(s in t for s in _SCOPE_WITHOUT_LEVEL)):
        return FilterResult(False, "no senior/lead signal in title")
    return FilterResult(True)


def location_filter(job: PortalJob, cfg: dict) -> FilterResult:
    loc_cfg = cfg["locations"]
    loc = (job.location or "").lower()
    country = job.country
    accept = [c.lower() for c in loc_cfg.get("accept_countries", ["Canada"])]
    remote_regions = [r.lower() for r in loc_cfg.get("accept_remote_anywhere_in", [])]

    # Multi-location postings: accept if any listed location is Canadian.
    if country and country.lower() in accept:
        return FilterResult(True)
    if "canada" in loc or any(r in loc for r in remote_regions if r != "canada"):
        return FilterResult(True)
    if country == "United States":
        if loc_cfg.get("accept_us_roles"):
            return FilterResult(True, flags=("us_role_verify_authorization",))
        return FilterResult(False, "US location")
    if country is None:
        if job.work_model == "remote" or not loc:
            return FilterResult(True, flags=("location_unverified",))
        return FilterResult(False, f"location outside target ({job.location})")
    return FilterResult(False, f"location outside target ({job.location})")


def company_filter(company: str, cfg: dict) -> FilterResult:
    c = (company or "").strip().lower()
    for ex in cfg.get("exclude_companies", []):
        if c == ex.lower() or c.startswith(ex.lower() + " "):
            return FilterResult(False, f"excluded company ({ex})")
    return FilterResult(True)


def prefilter(job: PortalJob, cfg: dict) -> FilterResult:
    flags: list[str] = []
    for check in (company_filter(job.company, cfg), title_filter(job.title, cfg),
                  location_filter(job, cfg)):
        if not check.keep:
            return check
        flags.extend(check.flags)
    return FilterResult(True, flags=tuple(flags))
