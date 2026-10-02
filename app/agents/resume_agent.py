"""
Resume-tailoring agent (Claude).

For each new Tier 1–2 job found by the scout, rewrites the master resume for
that posting under a strict rule: every claim must come from the master
resume or a `safe_claims` entry in the evidence library. Nothing new is
invented — no metrics, employers, titles, dates or tools.

Three layers keep it honest:
  1. Writer   — Claude tailors the resume and returns it as structured JSON,
                citing a source (master / evidence id) for each bullet.
  2. Checks   — deterministic Python: numbers, dates, employers, contact
                header and unsafe-claim phrases are verified against sources.
  3. Auditor  — a second Claude call reads tailored vs. sources and lists any
                unsupported statement. If issues remain after one revision,
                the resume is marked `needs_review` instead of `ready`.

Outputs per job: output/resumes/<Company>_<Title>.docx (+ .md and a short
change log), uploaded by the workflow as a private run artifact.

Requires ANTHROPIC_API_KEY. Model via ANTHROPIC_MODEL (default in app/agents/llm.py).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

from rapidfuzz import fuzz

log = logging.getLogger("resume_agent")

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = ROOT / "output" / "resumes"
from app.agents.llm import DEFAULT_MODEL, get_model, make_client, structured_call  # noqa: E402,F401
MAX_PER_RUN = int(os.getenv("MAX_RESUMES_PER_RUN", "8"))

WRITER_SYSTEM = """You tailor Elena Shchetinina's resume to a specific job posting.

HARD RULES — a violation makes the resume unusable:
1. Use ONLY facts found in the MASTER RESUME or in the `safe_claims` of the EVIDENCE LIBRARY.
   You may reorder, condense, re-emphasize and reword. You may surface a JD keyword only if a
   source already supports it (e.g. "ServiceNow" appears in a safe claim).
2. Never introduce a number, percentage, dollar amount, team size, date, employer, job title,
   certification, tool or technology that is not in the sources. Keep every number exactly as
   written (including "~" and "+").
3. Never use or paraphrase anything listed under `unsafe_claims`. Do not describe Elena as an
   enterprise architect, hands-on ML engineer, or as having built/developed AI models.
4. Keep every role (employer, title, location, dates) exactly as in the master resume, in the same
   order. Keep the header (name, contact line) and Education & Certifications verbatim.
5. Do not drop a role entirely; you may shorten older roles to fewer bullets.
6. If a JD requirement is not supported by the sources, leave it out and list it in
   `keywords_not_added` with the reason. Do not paper over gaps.

STYLE: senior TPM/portfolio leader voice; lead each bullet with the outcome or scope that matters
most for THIS posting; plain language; no buzzword stuffing; Canadian/US English spelling as in the
master. Professional summary 3–4 sentences tailored to the role. 10–16 core capabilities ordered by
relevance to the posting."""

AUDITOR_SYSTEM = """You are a strict fact-checker for resumes. Compare a TAILORED resume against
its SOURCES (master resume + evidence library safe claims). List every statement in the tailored
resume that is not supported by the sources: new numbers, scope, tools, titles, outcomes,
responsibilities, or any paraphrase of an unsafe claim. Rewording and condensing supported facts
is fine. Be specific and quote the problematic phrase. If everything is supported, return an
empty list."""

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Professional summary, 3-4 sentences."},
        "core_capabilities": {"type": "array", "items": {"type": "string"}},
        "roles": {
            "type": "array",
            "description": "Every role from the master resume, same order. Use the exact heading lines.",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string",
                                "description": "Exact role block heading lines from the master (### line, bold title line, italic line, and any sub-role bold lines), joined with newlines."},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "source": {"type": "string",
                                           "description": "'master' or an evidence id such as BELL-TCO-01"},
                            },
                            "required": ["text", "source"],
                        },
                    },
                },
                "required": ["heading", "bullets"],
            },
        },
        "tools_section": {"type": "string",
                          "description": "Tools & Technology section body, reordered for relevance; only items already in the master."},
        "keywords_added": {"type": "array", "items": {"type": "string"}},
        "keywords_not_added": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"keyword": {"type": "string"}, "reason": {"type": "string"}},
                      "required": ["keyword", "reason"]},
        },
    },
    "required": ["summary", "core_capabilities", "roles", "tools_section",
                 "keywords_added", "keywords_not_added"],
}

AUDIT_SCHEMA = {
    "type": "object",
    "properties": {"issues": {"type": "array", "items": {"type": "string"},
                              "description": "Each unsupported statement, quoting the phrase. Empty if none."}},
    "required": ["issues"],
}


# ---------------------------------------------------------------------------
# Source material
# ---------------------------------------------------------------------------

@dataclass
class Sources:
    master: str
    evidence: list[dict[str, Any]]
    constraints: list[str]

    @classmethod
    def load(cls) -> "Sources":
        master = (ROOT / "data" / "master_resume.txt").read_text(encoding="utf-8")
        evidence = json.loads((ROOT / "data" / "evidence_library.json").read_text(encoding="utf-8"))
        profile = json.loads((ROOT / "data" / "candidate_profile.json").read_text(encoding="utf-8"))
        return cls(master=master, evidence=evidence, constraints=profile.get("constraints", []))

    @property
    def safe_text(self) -> str:
        parts = [self.master]
        for e in self.evidence:
            parts.append(e.get("evidence") or "")
            parts.extend(e.get("safe_claims", []))
            parts.extend(e.get("metrics", []))
        return "\n".join(parts)

    @property
    def unsafe_claims(self) -> list[str]:
        return [c for e in self.evidence for c in e.get("unsafe_claims", [])]

    def evidence_for_prompt(self) -> str:
        slim = [{k: e.get(k) for k in ("id", "employer", "initiative", "capabilities",
                                       "technologies", "safe_claims", "unsafe_claims", "metrics")
                 if e.get(k)} for e in self.evidence]
        return json.dumps(slim, indent=1, ensure_ascii=False)


def split_master(master: str) -> dict[str, str]:
    """Header (before first ##), education block and the role headings, verbatim."""
    header = master.split("\n## ", 1)[0].strip()
    edu = re.search(r"(## Education[^\n]*\n.*?)(?=\n## |\Z)", master, re.S)
    return {"header": header, "education": edu.group(1).strip() if edu else ""}


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![A-Za-z])[~$]?\d[\d,.]*\s?(?:%|\+|k|K|M|B)?")
_DATE_RANGE_RE = re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}|\b(?:19|20)\d{2}\b")


def _norm_num(tok: str) -> str:
    return re.sub(r"[\s~,]", "", tok).rstrip(".").lower()


def deterministic_issues(tailored_md: str, sources: Sources) -> list[str]:
    issues: list[str] = []
    safe = sources.safe_text
    safe_nums = {_norm_num(t) for t in _NUM_RE.findall(safe)}

    for tok in set(_NUM_RE.findall(tailored_md)):
        n = _norm_num(tok)
        if not n or n in safe_nums:
            continue
        bare = re.sub(r"[%+kmb$]", "", n)
        if bare and any(re.sub(r"[%+kmb$]", "", s) == bare for s in safe_nums):
            continue
        issues.append(f"Number not found in sources: '{tok.strip()}'")

    for d in set(_DATE_RANGE_RE.findall(tailored_md)):
        if d not in safe:
            issues.append(f"Date not found in master resume: '{d}'")

    master_headings = re.findall(r"^### (.+)$", sources.master, re.M)
    for h in master_headings:
        if h.strip() not in tailored_md:
            issues.append(f"Role heading missing or altered: '{h.strip()}'")
    for h in re.findall(r"^### (.+)$", tailored_md, re.M):
        if h.strip() not in master_headings:
            issues.append(f"New role heading not in master: '{h.strip()}'")

    header = split_master(sources.master)["header"]
    if header and header not in tailored_md:
        issues.append("Header (name / contact line) was changed")

    sentences = re.split(r"(?<=[.;])\s+|\n", tailored_md)
    for claim in sources.unsafe_claims:
        for s in sentences:
            if len(s) > 15 and fuzz.partial_ratio(claim.lower(), s.lower()) >= 88:
                issues.append(f"Resembles an unsafe claim ('{claim}'): '{s.strip()[:120]}'")
                break
    return issues


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def role_sections(master: str) -> dict[str, str]:
    """Map each '### ' role heading to the '## ' section it sits under in the master."""
    mapping, section = {}, "Professional Experience"
    for line in master.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith("### "):
            mapping[line[4:].strip()] = section
    return mapping


def render_markdown(result: dict[str, Any], sources: Sources) -> str:
    parts = split_master(sources.master)
    sections = role_sections(sources.master)
    out = [parts["header"], "", "## Professional Summary", result["summary"].strip(), "",
           "## Core Capabilities", " • ".join(c.strip() for c in result["core_capabilities"]), ""]
    current = None
    for role in result["roles"]:
        heading = role["heading"].strip()
        m = re.search(r"^### (.+)$", heading, re.M)
        section = sections.get(m.group(1).strip(), current or "Professional Experience") if m \
            else (current or "Professional Experience")
        if section != current:
            out += [f"## {section}", ""]
            current = section
        out.append(heading)
        for b in role["bullets"]:
            out.append(f"• {b['text'].strip()}")
        out.append("")
    if parts["education"]:
        out += [parts["education"], ""]
    out += ["## Tools & Technology", result["tools_section"].strip(), ""]
    return "\n".join(out).strip() + "\n"


def _add_runs(paragraph, text: str) -> None:
    """Minimal inline markdown: **bold** and *italic*."""
    for token in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text):
        if not token:
            continue
        if token.startswith("**"):
            paragraph.add_run(token[2:-2]).bold = True
        elif token.startswith("*"):
            paragraph.add_run(token[1:-1]).italic = True
        else:
            paragraph.add_run(token)


def write_docx(markdown: str, path: Path) -> None:
    from docx import Document
    from docx.shared import Pt, Inches

    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(0.6)
        section.left_margin = section.right_margin = Inches(0.7)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)

    for line in markdown.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        if s.startswith("# "):
            p = doc.add_paragraph()
            run = p.add_run(s[2:].strip())
            run.bold = True
            run.font.size = Pt(18)
        elif s.startswith("## "):
            p = doc.add_heading(s[3:].strip(), level=2)
            p.paragraph_format.space_before = Pt(10)
        elif s.startswith("### "):
            p = doc.add_paragraph()
            run = p.add_run(s[4:].strip())
            run.bold = True
            run.font.size = Pt(11.5)
            p.paragraph_format.space_before = Pt(8)
        elif s.lstrip().startswith(("• ", "- ", "* ")):
            p = doc.add_paragraph(style="List Bullet")
            _add_runs(p, re.sub(r"^\s*[•\-*]\s+", "", s))
        else:
            p = doc.add_paragraph()
            _add_runs(p, s.strip())
        p.paragraph_format.space_after = Pt(2)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def safe_filename(company: str, title: str) -> str:
    base = f"{company}_{title}"
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    return f"Elena_Shchetinina_{base[:80]}"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@dataclass
class TailorOutcome:
    status: str                         # ready | needs_review | error
    markdown: str = ""
    issues: list[str] = field(default_factory=list)
    keywords_added: list[str] = field(default_factory=list)
    keywords_not_added: list[dict[str, str]] = field(default_factory=list)
    error: str = ""


class ResumeAgent:
    def __init__(self, client=None, model: Optional[str] = None, sources: Optional[Sources] = None):
        self.client = client or make_client()   # reads ANTHROPIC_API_KEY
        self.model = get_model(model)
        self.sources = sources or Sources.load()

    def _call(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
        return structured_call(self.client, self.model, system, user, schema, max_tokens)

    def _writer_prompt(self, job: dict, feedback: Optional[list[str]] = None,
                       user_feedback: str = "") -> str:
        p = (f"<job>\nCompany: {job['company']}\nTitle: {job['title']}\n"
             f"Location: {job.get('location') or 'n/a'}\n\n{job.get('description') or ''}\n</job>\n\n"
             f"<master_resume>\n{self.sources.master}\n</master_resume>\n\n"
             f"<evidence_library>\n{self.sources.evidence_for_prompt()}\n</evidence_library>\n\n"
             f"<candidate_constraints>\n" + "\n".join(self.sources.constraints) + "\n</candidate_constraints>")
        if user_feedback.strip():
            p += ("\n\n<candidate_feedback>\nElena reviewed an earlier draft for this job and asked for "
                  "these changes. Apply them as far as the sources allow; if a request needs a claim the "
                  "sources do not support, leave it out and say so in `keywords_not_added`.\n"
                  f"{user_feedback.strip()}\n</candidate_feedback>")
        if feedback:
            p += ("\n\nYour previous draft had these problems. Fix every one by removing or "
                  "rewording the statement so it is fully supported:\n- " + "\n- ".join(feedback))
        return p

    def _audit(self, tailored_md: str) -> list[str]:
        user = (f"<sources>\n<master_resume>\n{self.sources.master}\n</master_resume>\n"
                f"<evidence_library>\n{self.sources.evidence_for_prompt()}\n</evidence_library>\n</sources>\n\n"
                f"<tailored_resume>\n{tailored_md}\n</tailored_resume>")
        return list(self._call(AUDITOR_SYSTEM, user, AUDIT_SCHEMA, max_tokens=8000).get("issues", []))

    def tailor(self, job: dict, user_feedback: str = "") -> TailorOutcome:
        """
        Tailor the master resume to `job` (needs company, title, description).
        `user_feedback` carries the candidate's notes from rejecting an earlier draft.
        """
        feedback: Optional[list[str]] = None
        result, md, issues = None, "", []
        try:
            for attempt in range(2):
                result = self._call(
                    WRITER_SYSTEM, self._writer_prompt(job, feedback, user_feedback), TAILOR_SCHEMA)
                md = render_markdown(result, self.sources)
                issues = deterministic_issues(md, self.sources)
                if not issues:
                    issues = self._audit(md)
                if not issues:
                    break
                feedback = issues
        except Exception as exc:  # network, auth, schema
            log.exception("tailoring failed for %s", job.get("id"))
            return TailorOutcome(status="error", error=str(exc)[:300])
        return TailorOutcome(
            status="ready" if not issues else "needs_review",
            markdown=md,
            issues=issues,
            keywords_added=list(result.get("keywords_added", [])) if result else [],
            keywords_not_added=list(result.get("keywords_not_added", [])) if result else [],
        )


def write_outputs(outcome: TailorOutcome, job: dict, out_dir: Path, name: str) -> dict[str, Path]:
    """Write <name>.docx, <name>.md and <name>_NOTES.md for a tailored resume."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, docx_path, notes_path = (out_dir / f"{name}.md", out_dir / f"{name}.docx",
                                      out_dir / f"{name}_NOTES.md")
    md_path.write_text(outcome.markdown, encoding="utf-8")
    write_docx(outcome.markdown, docx_path)
    added = [f"- {k}" for k in outcome.keywords_added] or ["- none"]
    not_added = [f"- {k['keyword']}: {k['reason']}" for k in outcome.keywords_not_added] or ["- none"]
    notes = [f"# Tailoring notes — {job['company']}: {job['title']}", "",
             f"Status: {outcome.status}", f"Posting: {job.get('url')}", "",
             "## Keywords surfaced (supported by your sources)", *added, "",
             "## JD requirements NOT added (no supporting evidence)", *not_added]
    if outcome.issues:
        notes += ["", "## Fact-check issues to review before sending",
                  *[f"- {i}" for i in outcome.issues]]
    notes_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    return {"md": md_path, "docx": docx_path, "notes": notes_path}


# ---------------------------------------------------------------------------
# Batch over the scout store
# ---------------------------------------------------------------------------

def select_jobs(jobs: list[dict], limit: int = MAX_PER_RUN) -> list[dict]:
    """New open Tier 1–2 jobs without a resume yet; full-JD sources and higher fit first."""
    pending = [j for j in jobs
               if j.get("status") == "open" and j.get("tier") in ("tier_1", "tier_2")
               and not (j.get("resume") or {}).get("status") in ("ready", "needs_review")
               and j.get("description")]
    pending.sort(key=lambda j: ("partial_description" in (j.get("flags") or []),
                                -(j.get("fit_score") or 0)))
    return pending[:limit]


def run_batch(store=None, agent: Optional[ResumeAgent] = None, out_dir: Optional[Path] = None,
              limit: int = MAX_PER_RUN) -> list[dict]:
    from app.scout.store import JobStore

    store = store or JobStore.load()
    out_dir = Path(out_dir or OUTPUT_DIR)
    targets = select_jobs(list(store.jobs.values()), limit)
    if not targets:
        return []
    agent = agent or ResumeAgent()
    run_url = None
    if os.getenv("GITHUB_RUN_ID"):
        run_url = (f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}"
                   f"/actions/runs/{os.getenv('GITHUB_RUN_ID')}#artifacts")
    summary = []
    for job in targets:
        outcome = agent.tailor(job)
        rec: dict[str, Any] = {"status": outcome.status, "generated": date.today().isoformat(),
                               "model": agent.model}
        if outcome.status in ("ready", "needs_review"):
            name = safe_filename(job["company"], job["title"])
            write_outputs(outcome, job, out_dir, name)
            rec.update({"file": f"{name}.docx", "issues": outcome.issues[:10], "run_url": run_url,
                        "keywords_not_added": [k["keyword"] for k in outcome.keywords_not_added][:10]})
        else:
            rec["error"] = outcome.error
        store.jobs[job["id"]]["resume"] = rec
        summary.append({"job": job["id"], **{k: rec.get(k) for k in ("status", "file", "error")}})
    store.save()
    return summary
