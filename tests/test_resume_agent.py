"""Tests for the Claude resume agent, using a fake client (no network, no API key)."""
from __future__ import annotations

import copy
import re
from pathlib import Path
from types import SimpleNamespace as NS

from app.agents.resume_agent import (
    ResumeAgent, Sources, deterministic_issues, render_markdown, run_batch, select_jobs,
)
from app.scout.store import JobStore


def faithful_result(master: str) -> dict:
    """A draft that reuses the master resume verbatim — should pass every check."""
    exp = master.split("## Professional Experience", 1)[1]
    exp = re.split(r"\n## Education", exp)[0]
    exp = re.sub(r"\n## [^\n]+\n", "\n", exp)
    roles = []
    for block in re.split(r"\n(?=### )", exp.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        roles.append({
            "heading": "\n".join(l for l in lines if not l.lstrip().startswith("•")),
            "bullets": [{"text": l.lstrip("• ").strip(), "source": "master"}
                        for l in lines if l.lstrip().startswith("•")],
        })
    return {"summary": "Senior technical program and portfolio leader with 20+ years of experience.",
            "core_capabilities": ["Technical Program Management", "Portfolio Governance"],
            "roles": roles, "tools_section": master.split("## Tools & Technology", 1)[1].strip(),
            "keywords_added": ["ServiceNow"],
            "keywords_not_added": [{"keyword": "Kubernetes", "reason": "no supporting evidence"}]}


class FakeClient:
    def __init__(self, writer, audits):
        self.writer, self.audits, self.calls = list(writer), list(audits), []
        self.messages = self

    def create(self, **kw):
        name = kw["tool_choice"]["name"]
        self.calls.append(name)
        data = self.writer.pop(0) if name == "submit_tailored_resume" else {"issues": self.audits.pop(0)}
        return NS(content=[NS(type="tool_use", input=data)])


SRC = Sources.load()
GOOD = faithful_result(SRC.master)
JOB = {"id": "greenhouse:acme:1", "company": "Acme", "title": "Senior TPM, Payments",
       "description": "Lead programs.", "url": "https://x"}


def test_faithful_draft_passes_checks():
    assert deterministic_issues(render_markdown(GOOD, SRC), SRC) == []


def test_render_keeps_master_sections_and_header():
    md = render_markdown(GOOD, SRC)
    assert md.index("## Professional Experience") < md.index("## Earlier Telecom") < md.index("## Education")
    assert md.startswith("# Elena Shchetinina")


def test_fabricated_metric_and_unsafe_claim_are_caught():
    bad = copy.deepcopy(GOOD)
    bad["roles"][0]["bullets"][0]["text"] = "Developed AI models that cut costs by 42% across 9 business units."
    issues = " | ".join(deterministic_issues(render_markdown(bad, SRC), SRC))
    assert "42%" in issues and "'9'" in issues and "unsafe claim" in issues


def test_changed_dates_or_new_employer_are_caught():
    bad = copy.deepcopy(GOOD)
    bad["roles"][0]["heading"] = bad["roles"][0]["heading"].replace("Jul 2024", "Jan 2023")
    bad["roles"].append({"heading": "### Google | Toronto, ON", "bullets": []})
    issues = " | ".join(deterministic_issues(render_markdown(bad, SRC), SRC))
    assert "Jan 2023" in issues and "Google" in issues


def test_agent_revises_after_failed_checks():
    bad = copy.deepcopy(GOOD)
    bad["roles"][0]["bullets"][0]["text"] = "Grew revenue by 37%."
    agent = ResumeAgent(client=FakeClient([bad, GOOD], [[]]), model="test", sources=SRC)
    out = agent.tailor(JOB)
    assert out.status == "ready"
    assert agent.client.calls == ["submit_tailored_resume", "submit_tailored_resume", "submit_audit"]


def test_agent_marks_needs_review_when_auditor_keeps_objecting():
    agent = ResumeAgent(client=FakeClient([GOOD, GOOD], [["overstated scope"], ["still overstated"]]),
                        model="test", sources=SRC)
    out = agent.tailor(JOB)
    assert out.status == "needs_review" and out.issues == ["still overstated"]


def test_select_jobs_prefers_full_descriptions_and_skips_done():
    jobs = [
        {"id": "a", "status": "open", "tier": "tier_1", "fit_score": 90, "description": "d",
         "flags": ["partial_description"]},
        {"id": "b", "status": "open", "tier": "tier_2", "fit_score": 72, "description": "d", "flags": []},
        {"id": "c", "status": "open", "tier": "tier_1", "fit_score": 88, "description": "d",
         "resume": {"status": "ready"}},
        {"id": "d", "status": "open", "tier": "tier_3", "fit_score": 65, "description": "d"},
    ]
    assert [j["id"] for j in select_jobs(jobs, 5)] == ["b", "a"]


def test_run_batch_writes_files_and_updates_store(tmp_path: Path):
    store = JobStore(path=tmp_path / "jobs.json")
    store.jobs[JOB["id"]] = {**JOB, "status": "open", "tier": "tier_1", "fit_score": 84, "flags": []}
    agent = ResumeAgent(client=FakeClient([GOOD], [[]]), model="test", sources=SRC)
    results = run_batch(store=store, agent=agent, out_dir=tmp_path / "out")
    assert results[0]["status"] == "ready"
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert any(n.endswith(".docx") for n in names) and any(n.endswith("_NOTES.md") for n in names)
    assert store.jobs[JOB["id"]]["resume"]["file"].endswith(".docx")
