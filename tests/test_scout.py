"""Tests for the daily scout: board adapters, filters, store, pipeline, dashboard."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from app.integrations.adzuna_adapter import AdzunaAdapter
from app.integrations.ats_boards import (
    BoardNotFound, fetch_ashby, fetch_greenhouse, fetch_lever, html_to_text,
)
from app.integrations.portal_base import PortalJob
from app.scout import filters
from app.scout.dashboard import build
from app.scout.pipeline import load_config, run
from app.scout.store import JobStore

GH = {"jobs": [
    {"id": 1, "title": "Senior Technical Program Manager, Payments", "absolute_url": "https://gh/1",
     "location": {"name": "Toronto, Ontario, Canada"}, "updated_at": "2026-09-29T00:00:00Z",
     "content": "&lt;p&gt;Lead cross-functional programs, roadmap planning, dependency management, "
                "risk management and executive stakeholder management.&lt;/p&gt;"},
    {"id": 2, "title": "Senior Software Engineer", "absolute_url": "https://gh/2",
     "location": {"name": "Toronto"}, "content": "code"},
    {"id": 3, "title": "Director, Program Management", "absolute_url": "https://gh/3",
     "location": {"name": "San Francisco, CA"}, "content": "x"},
]}
LEVER = [{"id": "lv1", "text": "Principal Portfolio Manager", "hostedUrl": "https://lever/1",
          "categories": {"location": "Remote - Canada", "team": "PMO"}, "workplaceType": "remote",
          "descriptionPlain": "Portfolio governance and roadmap.", "lists": [
              {"text": "What you'll do", "content": "<li>Run intake</li><li>Own LRP</li>"}],
          "createdAt": 1759190400000}]
ASHBY = {"jobs": [{"id": "ab1", "title": "Lead Program Manager, AI Platform", "location": "Toronto, ON",
                   "workplaceType": "Hybrid", "descriptionPlain": "AI program delivery.",
                   "jobUrl": "https://ashby/1", "publishedAt": "2026-09-28T12:00:00Z",
                   "compensation": {"compensationTierSummary": "CA$180K – CA$220K"}},
                  {"id": "ab2", "title": "Hidden", "isListed": False}]}


def _client(routes: dict[str, object]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        for frag, body in routes.items():
            if frag in str(req.url):
                return httpx.Response(200, json=body)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def _cfg(watchlist):
    cfg = load_config()
    cfg["watchlist"] = watchlist
    return cfg


NO_ADZUNA = AdzunaAdapter(app_id="", app_key="")


# --- adapters ---------------------------------------------------------------

def test_html_to_text_unescapes_greenhouse_content():
    assert html_to_text("&lt;p&gt;Hello &amp;amp; bye&lt;/p&gt;") == "Hello & bye"


def test_greenhouse_parsing():
    jobs = fetch_greenhouse("acme", "Acme", _client({"/boards/acme/": GH}))
    assert len(jobs) == 3
    j = jobs[0]
    assert j.country == "Canada" and j.url == "https://gh/1" and "roadmap planning" in j.description
    assert j.source_type == "official_career"


def test_lever_parsing_includes_lists():
    j = fetch_lever("acme", "Acme", _client({"/postings/acme": LEVER}))[0]
    assert j.work_model == "remote" and j.country == "Canada"
    assert "Run intake" in j.description and j.posted_date == "2025-09-30"


def test_ashby_skips_unlisted_and_keeps_comp():
    jobs = fetch_ashby("acme", "Acme", _client({"/job-board/acme": ASHBY}))
    assert len(jobs) == 1
    assert jobs[0].work_model == "hybrid" and jobs[0].raw["compensation"] == "CA$180K – CA$220K"


def test_missing_board_raises_not_found():
    with pytest.raises(BoardNotFound):
        fetch_greenhouse("nope", "Nope", _client({}))


def test_adzuna_unconfigured_returns_nothing():
    assert NO_ADZUNA.search("tpm") == []


def test_adzuna_normalize_flags_partial_description():
    j = AdzunaAdapter._normalize({"id": 9, "title": "<strong>Senior</strong> Program Manager",
                                  "description": "snippet", "redirect_url": "https://adz/9",
                                  "company": {"display_name": "RBC"},
                                  "location": {"display_name": "Toronto, Ontario"},
                                  "created": "2026-09-30T08:00:00Z"})
    assert j.title == "Senior Program Manager" and j.company == "RBC"
    assert j.raw["partial_description"] is True and j.posted_date == "2026-09-30"


# --- filters ----------------------------------------------------------------

def _pj(title, location="Toronto, ON", country="Canada", company="Acme", work_model=None):
    return PortalJob(portal="t", external_id="1", title=title, company=company, location=location,
                     country=country, work_model=work_model, url="u", source_type="t",
                     description="", posted_date=None)


@pytest.mark.parametrize("title,keep", [
    ("Senior Technical Program Manager", True),
    ("Technical Program Manager, Payments", True),          # unlevelled TPM title
    ("Director, Portfolio Management", True),
    ("Program Manager", False),                              # no seniority signal
    ("Senior Software Engineer", False),
    ("Program Coordinator", False),
    ("Senior Marketing Program Manager", False),
])
def test_title_filter(title, keep):
    assert filters.title_filter(title, load_config()).keep is keep


def test_location_filter_rules():
    cfg = load_config()
    assert filters.location_filter(_pj("x"), cfg).keep
    assert not filters.location_filter(_pj("x", "Seattle, WA", "United States"), cfg).keep
    r = filters.location_filter(_pj("x", "Remote", None, work_model="remote"), cfg)
    assert r.keep and "location_unverified" in r.flags


@pytest.mark.parametrize("location,country,keep", [
    # The four wrong-location matches found in the first real scout runs.
    ("Remote - US: Select locations", "United States", False),
    ("Korea", "Other", False),
    ("San Francisco, CA • New York, NY • United States", "United States", False),
    # Still accepted
    ("Toronto, Ontario, Canada", "Canada", True),
    ("United States; Canada", "Canada", True),
    ("Austin, Texas, United States; Toronto, Ontario, Canada", "Canada", True),
    ("Ontario - Remote", "Canada", True),
    ("Remote - North America", None, True),
    ("Remote", None, True),
    # Remote roles tied to a place outside Canada, or a place we cannot identify
    ("Remote, EMEA", "Other", False),
    ("London, UK", "Other", False),
    ("Bucharest", None, False),
])
def test_country_guess_and_location_filter(location, country, keep):
    from app.integrations.ats_boards import guess_country
    assert guess_country(location) == country
    job = _pj("x", location, guess_country(location), work_model="remote")
    assert filters.location_filter(job, load_config()).keep is keep


def test_greenhouse_country_comes_from_the_posting_not_the_office_list():
    board = {"jobs": [{"id": 9, "title": "Senior Technical Program Manager", "absolute_url": "https://gh/9",
                       "location": {"name": "Remote - US: Select locations"},
                       "offices": [{"name": "Toronto, Ontario, Canada"}, {"name": "San Francisco, CA"}],
                       "content": "x"}]}
    job = fetch_greenhouse("acme", "Acme", _client({"/boards/acme/": board}))[0]
    assert job.country == "United States"
    assert not filters.prefilter(job, load_config()).keep


def test_stored_job_that_now_fails_filters_is_retired_with_reason(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    store.jobs["greenhouse:acme:3"] = {"id": "greenhouse:acme:3", "status": "open", "source": "board",
                                       "source_key": "greenhouse:acme", "company": "Acme",
                                       "title": "Director, Program Management",
                                       "identity": "acme|director program management",
                                       "last_seen": "2026-09-30", "description": "x"}
    cfg = _cfg([{"company": "Acme", "ats": "greenhouse", "slug": "acme"}])
    r = run(store=store, cfg=cfg, client=_client({"/boards/acme/": GH}), adzuna=NO_ADZUNA,
            today=date(2026, 10, 1))
    rec = store.jobs["greenhouse:acme:3"]            # GH job 3 is in San Francisco
    assert rec["status"] == "filtered_out" and rec["filter_reason"] == "US location"
    assert r.filtered_out == 1 and r.closed == 0


def test_excluded_companies():
    cfg = load_config()
    assert not filters.prefilter(_pj("Senior Technical Program Manager", company="Amazon"), cfg).keep
    assert not filters.prefilter(_pj("Senior Technical Program Manager", company="CGI"), cfg).keep


# --- pipeline + store ---------------------------------------------------------

def test_pipeline_new_then_closed(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    cfg = _cfg([{"company": "Acme", "ats": "greenhouse", "slug": "acme"},
                {"company": "Gone", "ats": "lever", "slug": "gone"}])
    r = run(store=store, cfg=cfg, client=_client({"/boards/acme/": GH}), adzuna=NO_ADZUNA,
            today=date(2026, 10, 1))
    assert r.fetched == 3 and r.passed_filter == 1 and r.new == 1
    assert any(e["source"] == "lever:gone" for e in r.source_errors)
    rec = next(iter(store.jobs.values()))
    assert rec["tier"] == "tier_1" and rec["status"] == "open"
    assert (tmp_path / "jobs.json").exists()

    # Next day the posting is gone from a healthy board → closed.
    r2 = run(store=store, cfg=cfg, client=_client({"/boards/acme/": {"jobs": GH["jobs"][1:]}}),
             adzuna=NO_ADZUNA, today=date(2026, 10, 2))
    assert r2.closed == 1 and rec["status"] == "closed" and "description" not in rec


def test_pipeline_does_not_close_jobs_when_board_fails(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    cfg = _cfg([{"company": "Acme", "ats": "greenhouse", "slug": "acme"}])
    run(store=store, cfg=cfg, client=_client({"/boards/acme/": GH}), adzuna=NO_ADZUNA,
        today=date(2026, 10, 1))
    r = run(store=store, cfg=cfg, client=_client({}), adzuna=NO_ADZUNA, today=date(2026, 10, 2))
    assert r.closed == 0 and all(j["status"] == "open" for j in store.jobs.values())


def test_board_listing_replaces_aggregator_duplicate(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    store.jobs["adzuna:9"] = {"id": "adzuna:9", "identity": "acme|senior technical program manager payments",
                              "source": "adzuna", "status": "open", "last_seen": "2026-09-30",
                              "company": "Acme", "title": "Senior Technical Program Manager, Payments"}
    cfg = _cfg([{"company": "Acme", "ats": "greenhouse", "slug": "acme"}])
    run(store=store, cfg=cfg, client=_client({"/boards/acme/": GH}), adzuna=NO_ADZUNA,
        today=date(2026, 10, 1))
    assert "adzuna:9" not in store.jobs and "greenhouse:acme:1" in store.jobs


def test_aggregator_jobs_expire(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    store.jobs["adzuna:1"] = {"id": "adzuna:1", "source": "adzuna", "status": "open", "last_seen": "2026-09-01"}
    assert store.close_missing(set(), set(), date(2026, 10, 1)) == 1
    assert store.jobs["adzuna:1"]["status"] == "expired"


# --- scoring regression ---------------------------------------------------------

def test_core_target_role_is_tier_one():
    """Regression: avoid-list word matching used to push every TPM role to Do Not Pursue."""
    from app.models import JobRecord
    from app.services import fit_estimator, gate_engine, jd_parser
    jd = ("Senior Technical Program Manager. Lead cross-functional programs, roadmap, dependency "
          "management, risk management, stakeholder management, Agile, data platform. Toronto, Ontario.")
    job = JobRecord(company="Acme", title="Senior Technical Program Manager", description=jd,
                    location="Toronto, ON")
    parsed = jd_parser.parse_jd(jd, company="Acme")
    fit = fit_estimator.estimate_fit(job, parsed, gate_engine.evaluate_gates(job, parsed))
    assert fit.tier.value == "tier_1"


def test_pure_product_manager_is_penalized_but_program_scope_is_not():
    from app.services.fit_estimator import _avoid_match
    assert _avoid_match("Senior Product Manager")
    assert _avoid_match("Senior Software Engineer")
    assert _avoid_match("Product Manager, Program Operations") is None
    assert _avoid_match("Senior Technical Program Manager") is None


# --- dashboard ------------------------------------------------------------------

def test_dashboard_excludes_descriptions(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    store.jobs["a"] = {"id": "a", "status": "open", "tier": "tier_1", "fit_score": 84.0,
                       "ats_readiness": 70.0, "company": "Acme", "title": "Senior TPM",
                       "first_seen": "2026-10-01", "url": "https://x", "source": "board",
                       "description": "SECRET-JD-TEXT"}
    store.jobs["b"] = {"id": "b", "status": "open", "tier": "do_not_pursue", "fit_score": 40.0,
                       "company": "Other", "title": "Skip me", "first_seen": "2026-10-01"}
    out = build(store, tmp_path / "site" / "index.html", today=date(2026, 10, 1))
    page = out.read_text()
    assert "Senior TPM" in page and "SECRET-JD-TEXT" not in page and "Skip me" not in page
