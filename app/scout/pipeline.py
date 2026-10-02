"""
Daily scout pipeline.

  1. Pull every opening from the watchlist boards (Greenhouse / Lever / Ashby).
  2. Pull recent postings from Adzuna for the configured queries.
  3. Pre-filter by company, title family/seniority and location.
  4. Deduplicate against the store (by source id, then company+title).
  5. Score new jobs with the existing engines: JD parser → hard gates →
     strategic fit → ATS readiness against the master resume.
  6. Close jobs that disappeared from healthy boards; save the store.

The scoring engines are deterministic Python — no API key needed for this
part. The resume agent runs afterwards as a separate step.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from app.integrations.adzuna_adapter import AdzunaAdapter
from app.integrations.ats_boards import USER_AGENT, BoardError, BoardNotFound, fetch_board
from app.integrations.portal_base import PortalJob
from app.models import JobRecord
from app.scout.filters import prefilter
from app.scout.store import JobStore, normalize_key

log = logging.getLogger("scout")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "data" / "scout" / "config.json"

# Keep stored descriptions bounded; the resume agent only needs the substance.
MAX_DESCRIPTION_CHARS = 12000


def load_config(path: Optional[Path] = None) -> dict:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


@dataclass
class RunReport:
    started_at: str
    fetched: int = 0
    passed_filter: int = 0
    new: int = 0
    updated: int = 0
    closed: int = 0
    filtered_out: int = 0
    new_tier1: int = 0
    new_tier2: int = 0
    source_errors: list[dict[str, str]] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_job(job: PortalJob, resume_text: str, evidence: list) -> dict[str, Any]:
    """Run the existing analysis engines on one posting (no DB writes)."""
    from app.services import ats_engine, fit_estimator, gate_engine, jd_parser

    description = job.description or ""
    text = f"{job.title}\n{job.location or ''}\n{description}".strip()
    record = JobRecord(company=job.company, title=job.title, description=text,
                       location=job.location, country=job.country, work_model=job.work_model,
                       official_url=job.url, source_type=job.source_type)
    parsed = jd_parser.parse_jd(text, company=job.company)
    gate = gate_engine.evaluate_gates(record, parsed)
    fit = fit_estimator.estimate_fit(record, parsed, gate)
    ats = ats_engine.assess(keywords=parsed.keywords + parsed.must_haves + parsed.preferred,
                            resume_text=resume_text, evidence=evidence, role_title=job.title)

    matched = [m.keyword for m in ats.matches if m.exact_match or m.semantic_match]
    missing_supported = [m.keyword for m in ats.matches
                         if not (m.exact_match or m.semantic_match) and m.evidence_ids]
    missing_unsupported = [m.keyword for m in ats.matches
                           if not (m.exact_match or m.semantic_match) and not m.evidence_ids]
    return {
        "role_family": parsed.role_family,
        "seniority": parsed.seniority,
        "fit_score": round(fit.weighted_score, 1),
        "tier": fit.tier.value,
        "ats_readiness": round(ats.readiness, 1),
        "barriers": list(gate.barriers),
        "authorization": gate.authorization_status,
        "matched_keywords": _dedupe(matched)[:15],
        "missing_supported": _dedupe(missing_supported)[:10],
        "missing_unsupported": _dedupe(missing_unsupported)[:10],
        "fit_notes": {k: getattr(fit, k).rationale for k in
                      ("functional", "seniority", "location_auth", "evidence")},
    }


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        k = i.lower()
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(cfg: dict, report: RunReport, client: Optional[httpx.Client] = None,
             adzuna: Optional[AdzunaAdapter] = None) -> tuple[list[tuple[str, PortalJob]], set[str]]:
    """Return [(source_key, job)] and the set of board source keys that fetched cleanly."""
    found: list[tuple[str, PortalJob]] = []
    healthy: set[str] = set()
    own = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT},
                                    follow_redirects=True)
    try:
        for entry in cfg.get("watchlist", []):
            source_key = f"{entry['ats']}:{entry['slug']}"
            try:
                jobs = fetch_board(entry["ats"], entry["slug"], entry["company"], client)
            except BoardNotFound:
                report.source_errors.append({"source": source_key, "company": entry["company"],
                                             "error": "board not found — slug may have changed"})
                continue
            except (BoardError, ValueError) as exc:
                report.source_errors.append({"source": source_key, "company": entry["company"],
                                             "error": str(exc)[:200]})
                continue
            healthy.add(source_key)
            report.sources[entry["company"]] = len(jobs)
            found.extend((source_key, j) for j in jobs)

        adzuna = adzuna or AdzunaAdapter()
        if adzuna.configured:
            total = 0
            for q in cfg.get("adzuna_queries", []):
                jobs = adzuna.search(q, max_results=100)
                total += len(jobs)
                found.extend(("adzuna", j) for j in jobs)
            report.sources["Adzuna (all queries)"] = total
        else:
            report.source_errors.append({"source": "adzuna", "company": "—",
                                         "error": "not configured (set ADZUNA_APP_ID / ADZUNA_APP_KEY)"})
    finally:
        if own:
            client.close()
    report.fetched = len(found)
    return found, healthy


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(store: Optional[JobStore] = None, cfg: Optional[dict] = None,
        client: Optional[httpx.Client] = None, adzuna: Optional[AdzunaAdapter] = None,
        today: Optional[date] = None) -> RunReport:
    from app.orchestrator import load_master_resume
    from app.services.evidence_loader import load_evidence_library

    cfg = cfg or load_config()
    store = store or JobStore.load()
    today = today or date.today()
    report = RunReport(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    resume_text = load_master_resume(allow_fallback=True)
    evidence = load_evidence_library()

    found, healthy = discover(cfg, report, client, adzuna)
    seen_ids: set[str] = set()

    for source_key, job in found:
        verdict = prefilter(job, cfg)
        jid = f"{source_key}:{job.external_id}"
        if not verdict.keep:
            # A job stored under older, looser filters: retire it with the reason
            # rather than letting it look like the employer closed the posting.
            stale = store.jobs.get(jid)
            if stale and stale.get("status") == "open":
                stale.update(status="filtered_out", closed_on=today.isoformat(),
                             filter_reason=verdict.reason)
                stale.pop("description", None)
                seen_ids.add(jid)
                report.filtered_out += 1
            continue
        report.passed_filter += 1
        source = "adzuna" if source_key == "adzuna" else "board"

        if jid not in store.jobs:
            # Same opening already known from another source (prefer the official board).
            twin = store.find_by_identity(job.company, job.title)
            if twin:
                twin_rec = store.jobs[twin]
                if source == "board" and twin_rec.get("source") == "adzuna":
                    # Upgrade an aggregator listing to the official posting (full JD, direct link).
                    del store.jobs[twin]
                else:
                    twin_rec["last_seen"] = today.isoformat()
                    seen_ids.add(twin)
                    continue

        if jid in store.jobs:
            rec = store.jobs[jid]
            rec["last_seen"] = today.isoformat()
            if rec.get("status") != "open":
                rec["status"] = "open"
                rec.pop("closed_on", None)
            report.updated += 1
            seen_ids.add(jid)
            continue

        scored = score_job(job, resume_text, evidence)
        store.jobs[jid] = {
            "id": jid,
            "identity": normalize_key(job.company, job.title),
            "source": source,
            "source_key": source_key,
            "portal": job.portal,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "country": job.country,
            "work_model": job.work_model,
            "url": job.url,
            "posted_date": job.posted_date,
            "first_seen": today.isoformat(),
            "last_seen": today.isoformat(),
            "status": "open",
            "flags": list(verdict.flags)
                     + (["partial_description"] if job.raw.get("partial_description") else []),
            "compensation": job.raw.get("compensation"),
            "description": (job.description or "")[:MAX_DESCRIPTION_CHARS],
            **scored,
        }
        seen_ids.add(jid)
        report.new += 1
        if scored["tier"] == "tier_1":
            report.new_tier1 += 1
        elif scored["tier"] == "tier_2":
            report.new_tier2 += 1

    report.closed = store.close_missing(seen_ids, healthy, today)
    store.prune(today)
    store.runs.append(report.as_dict())
    store.save()
    return report
