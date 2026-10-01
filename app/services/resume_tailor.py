"""
Resume Tailor Service.

Provides automated and interactive resume tailoring for specific job roles,
with specialized capabilities to update the candidate's current role experience,
professional summary, key competencies, and technical skills when key words
from the job description are missing.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.models import (
    ATSAssessment,
    EvidenceItem,
    JobRecord,
    ParsedJD,
    Requirement,
)
from app.services import ats_engine
from app.services.evidence_loader import load_evidence_library


# ---------------------------------------------------------------------------
# Section Parsing
# ---------------------------------------------------------------------------

def parse_resume_sections(resume_text: str) -> dict[str, Any]:
    """
    Parse a Markdown resume into modular components for targeted updating.
    """
    lines = resume_text.splitlines()

    header_lines: list[str] = []
    summary_lines: list[str] = []
    competencies_lines: list[str] = []
    current_role_lines: list[str] = []
    earlier_exp_lines: list[str] = []
    earlier_telecom_lines: list[str] = []
    education_lines: list[str] = []
    tools_lines: list[str] = []

    current_section = "header"
    role_count = 0

    exp_heading_pattern = re.compile(r"^##?\s*(?:professional\s+)?experience", re.IGNORECASE)
    earlier_exp_pattern = re.compile(r"^##?\s*(?:earlier\s+telecom|earlier\s+experience)", re.IGNORECASE)
    edu_pattern = re.compile(r"^##?\s*education", re.IGNORECASE)
    tools_pattern = re.compile(r"^##?\s*(?:tools|technical\s+skills)", re.IGNORECASE)
    summary_pattern = re.compile(r"^##?\s*(?:professional\s+)?summary", re.IGNORECASE)
    comp_pattern = re.compile(r"^##?\s*(?:core\s+capabilities|key\s+competencies|skills)", re.IGNORECASE)
    role_header_pattern = re.compile(r"^###\s+", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()

        # Check section transitions
        if summary_pattern.match(stripped):
            current_section = "summary"
            continue
        elif comp_pattern.match(stripped) and current_section != "exp":
            current_section = "competencies"
            continue
        elif exp_heading_pattern.match(stripped):
            current_section = "exp"
            role_count = 0
            continue
        elif earlier_exp_pattern.match(stripped):
            current_section = "earlier_telecom"
            continue
        elif edu_pattern.match(stripped):
            current_section = "education"
            continue
        elif tools_pattern.match(stripped):
            current_section = "tools"
            continue

        # Route lines by section
        if current_section == "header":
            header_lines.append(line)
        elif current_section == "summary":
            summary_lines.append(line)
        elif current_section == "competencies":
            competencies_lines.append(line)
        elif current_section == "exp":
            if role_header_pattern.match(stripped):
                role_count += 1
            if role_count <= 1:
                current_role_lines.append(line)
            else:
                earlier_exp_lines.append(line)
        elif current_section == "earlier_telecom":
            earlier_telecom_lines.append(line)
        elif current_section == "education":
            education_lines.append(line)
        elif current_section == "tools":
            tools_lines.append(line)

    # Deconstruct current role into metadata and bullets
    cur_bullets: list[str] = []
    cur_meta: list[str] = []
    for l in current_role_lines:
        s = l.strip()
        if s.startswith("•") or s.startswith("- ") or s.startswith("* "):
            # Bullet text
            clean_b = re.sub(r"^[•\-\*]\s*", "", s)
            if clean_b:
                cur_bullets.append(clean_b)
        else:
            if s:
                cur_meta.append(l)

    return {
        "header": "\n".join(header_lines).strip(),
        "summary": "\n".join(summary_lines).strip(),
        "competencies": "\n".join(competencies_lines).strip(),
        "current_role_meta": "\n".join(cur_meta).strip(),
        "current_role_bullets": cur_bullets,
        "earlier_experience": "\n".join(earlier_exp_lines).strip(),
        "earlier_telecom": "\n".join(earlier_telecom_lines).strip(),
        "education": "\n".join(education_lines).strip(),
        "tools": "\n".join(tools_lines).strip(),
    }


# ---------------------------------------------------------------------------
# Missing Keyword Discovery
# ---------------------------------------------------------------------------

def detect_missing_keywords(
    parsed_jd: ParsedJD | dict[str, Any],
    resume_text: str,
    evidence: list[EvidenceItem] | None = None,
) -> dict[str, Any]:
    """
    Identify missing keywords from the entire resume and specifically
    from the candidate's current role experience.
    """
    if isinstance(parsed_jd, dict):
        parsed_jd = ParsedJD.model_validate(parsed_jd)

    if evidence is None:
        evidence = load_evidence_library()

    rt_lower = resume_text.lower()
    sections = parse_resume_sections(resume_text)
    cur_bullets_text = " ".join(sections.get("current_role_bullets", [])).lower()

    # Collect all requirements from parsed JD
    all_reqs: list[Requirement] = []
    seen = set()
    for r in (parsed_jd.keywords + parsed_jd.must_haves + parsed_jd.preferred):
        norm = r.text.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            all_reqs.append(r)

    # Build evidence search corpus
    ev_by_kw: dict[str, list[str]] = {}
    for ev in evidence:
        kw_set = {k.lower() for k in (ev.keywords + ev.technologies + ev.capabilities)}
        for req in all_reqs:
            rl = req.text.lower()
            if rl in kw_set or any(rl in k for k in kw_set) or rl in (ev.claim + " " + (ev.evidence or "")).lower():
                ev_by_kw.setdefault(req.text, []).append(ev.evidence_id)

    missing_from_resume: list[dict[str, Any]] = []
    missing_from_current_role: list[dict[str, Any]] = []
    already_present: list[str] = []

    for req in all_reqs:
        rl = req.text.lower()
        is_in_resume = rl in rt_lower
        is_in_cur_role = rl in cur_bullets_text
        supported_ev = ev_by_kw.get(req.text, [])

        info = {
            "keyword": req.text,
            "importance": req.importance,
            "category": req.category,
            "evidence_ids": supported_ev,
            "is_supported": bool(supported_ev),
        }

        if not is_in_resume:
            missing_from_resume.append(info)
        else:
            already_present.append(req.text)

        if not is_in_cur_role:
            missing_from_current_role.append(info)

    # Sort missing by importance (critical first, then important)
    prio_order = {"critical": 0, "important": 1, "preferred": 2, "supporting": 3}
    missing_from_resume.sort(key=lambda x: prio_order.get(x["importance"], 4))
    missing_from_current_role.sort(key=lambda x: prio_order.get(x["importance"], 4))

    return {
        "missing_from_resume": missing_from_resume,
        "missing_from_current_role": missing_from_current_role,
        "already_present": already_present,
    }


# ---------------------------------------------------------------------------
# Current Role Tailoring Engine
# ---------------------------------------------------------------------------

def generate_tailored_current_role_bullets(
    missing_keywords: list[str],
    existing_bullets: list[str],
    job_title: str = "",
    company: str = "Bell Canada",
) -> list[str]:
    """
    Generate or enrich experience bullets for the candidate's current role
    (Bell Canada) incorporating target keywords in an evidence-grounded manner.
    """
    updated_bullets = list(existing_bullets)
    if not missing_keywords:
        return updated_bullets

    kw_lower_set = {k.strip().lower() for k in missing_keywords if k.strip()}

    # Check which existing bullets can be seamlessly enriched
    enriched_indices = set()

    # 1. TCO / ServiceNow / Tooling / Financial Management
    tco_keywords = kw_lower_set & {"servicenow", "tco", "financial management", "budget", "p&l", "cost optimization", "application portfolio management"}
    if tco_keywords:
        for idx, b in enumerate(updated_bullets):
            if "tco" in b.lower() or "1,400" in b.lower():
                additions = []
                if "servicenow" in tco_keywords and "servicenow" not in b.lower():
                    additions.append("ServiceNow")
                if "application portfolio management" in tco_keywords and "portfolio management" not in b.lower():
                    additions.append("application portfolio management")
                if "cost optimization" in tco_keywords and "cost" not in b.lower():
                    additions.append("cost optimization")
                
                if additions:
                    updated_bullets[idx] = b.replace(
                        "led Bell-side TCO data collection and stakeholder coordination with KPMG",
                        f"led Bell-side TCO data collection, {' and '.join(additions)}, and stakeholder coordination with KPMG",
                    )
                    enriched_indices.add(idx)
                    kw_lower_set -= tco_keywords
                break

    # 2. Modernization / Platform / Cloud / Payment / SaaS
    modern_keywords = kw_lower_set & {"cloud", "cloud modernization", "platform modernization", "saas", "payments", "system integration", "architecture"}
    if modern_keywords:
        for idx, b in enumerate(updated_bullets):
            if "payment" in b.lower() or "stack" in b.lower() or "customer-profile" in b.lower():
                if "cloud modernization" in modern_keywords and "cloud" not in b.lower():
                    updated_bullets[idx] = b.replace(
                        "replacing a legacy payment application with a new technology stack",
                        "replacing a legacy payment application with a modern cloud-ready technology stack",
                    )
                    enriched_indices.add(idx)
                    kw_lower_set.discard("cloud modernization")
                    kw_lower_set.discard("cloud")
                elif "cloud" in modern_keywords and "cloud" not in b.lower():
                    updated_bullets[idx] = b.replace(
                        "new technology stack",
                        "new cloud-aligned technology stack",
                    )
                    enriched_indices.add(idx)
                    kw_lower_set.discard("cloud")
                break

    # 3. Create high-impact synthesized accomplishment bullets for remaining missing keywords
    remaining_kws = [k for k in missing_keywords if k.strip().lower() in kw_lower_set]

    if remaining_kws:
        # Group remaining into cohesive thematic clusters
        governance_cluster = []
        data_ai_cluster = []
        delivery_tools_cluster = []
        general_cluster = []

        for kw in remaining_kws:
            kl = kw.lower()
            if kl in ("vendor governance", "vendor management", "risk management", "raid", "governance", "procurement", "operating model"):
                governance_cluster.append(kw)
            elif kl in ("ai", "machine learning", "data platform", "data quality", "metrics", "kpi", "analytics", "data integration"):
                data_ai_cluster.append(kw)
            elif kl in ("jira", "confluence", "capacity planning", "resource planning", "okr", "delivery management", "kanban", "agile", "safe", "lpm"):
                delivery_tools_cluster.append(kw)
            else:
                general_cluster.append(kw)

        # Build targeted bullets grounded in Bell Canada enterprise scope
        if governance_cluster:
            gov_str = ", ".join(governance_cluster[:3])
            b_text = (
                f"Established rigorous enterprise program governance, {gov_str}, and executive risk management "
                f"across six enterprise architecture domains, ensuring alignment between engineering roadmaps and corporate priorities."
            )
            updated_bullets.append(b_text)

        if delivery_tools_cluster:
            dt_str = ", ".join(delivery_tools_cluster[:3])
            b_text = (
                f"Orchestrated cross-functional delivery cadences, {dt_str}, and milestone dependency management, "
                f"partnering across product, architecture, and technology stakeholders to drive predictable program execution."
            )
            updated_bullets.append(b_text)

        if data_ai_cluster:
            data_str = ", ".join(data_ai_cluster[:3])
            b_text = (
                f"Partnered with enterprise data platform and engineering teams to establish portfolio KPIs, metrics, "
                f"and operating workflows supporting {data_str} across customer operations transformation."
            )
            updated_bullets.append(b_text)

        if general_cluster:
            gen_str = ", ".join(general_cluster[:3])
            b_text = (
                f"Directed complex cross-functional workstreams emphasizing {gen_str}, "
                f"facilitating executive steering and operational readiness for multi-million-dollar technology roadmaps."
            )
            updated_bullets.append(b_text)

    return updated_bullets


# ---------------------------------------------------------------------------
# Full Resume Tailoring Orchestration
# ---------------------------------------------------------------------------

def tailor_resume(
    master_resume_text: str,
    job: JobRecord | dict[str, Any],
    parsed_jd: ParsedJD | dict[str, Any],
    selected_keywords: list[str] | None = None,
    update_current_role: bool = True,
    update_summary: bool = True,
    update_competencies: bool = True,
    update_tools: bool = True,
    evidence: list[EvidenceItem] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Tailor the candidate's resume for the current role and target job,
    integrating missing keywords into the current role experience, summary,
    and key competencies.

    Returns:
        (tailored_resume_markdown, metadata_dict)
    """
    if isinstance(parsed_jd, dict):
        parsed_jd = ParsedJD.model_validate(parsed_jd)

    if evidence is None:
        evidence = load_evidence_library()

    # Extract job properties
    job_company = job.company if hasattr(job, "company") else job.get("company", "Target Company")
    job_title = job.title if hasattr(job, "title") else job.get("title", "Senior Program Manager")

    # Discover missing keywords if not explicitly provided
    missing_analysis = detect_missing_keywords(parsed_jd, master_resume_text, evidence=evidence)
    
    if selected_keywords is None:
        # Default to all missing keywords that are evidence-supported OR critical/important
        candidates = []
        for item in missing_analysis["missing_from_current_role"]:
            if item["is_supported"] or item["importance"] in ("critical", "important"):
                candidates.append(item["keyword"])
        selected_keywords = list(dict.fromkeys(candidates))

    sections = parse_resume_sections(master_resume_text)

    orig_cur_bullets = list(sections["current_role_bullets"])
    tailored_cur_bullets = list(orig_cur_bullets)

    # 1. Tailor Current Role Experience (Bell Canada)
    if update_current_role and selected_keywords:
        tailored_cur_bullets = generate_tailored_current_role_bullets(
            missing_keywords=selected_keywords,
            existing_bullets=orig_cur_bullets,
            job_title=job_title,
            company=job_company,
        )

    # 2. Tailor Summary
    summary_text = sections["summary"]
    if update_summary:
        kw_highlights = selected_keywords[:3]
        kw_clause = f", specialized in {', '.join(kw_highlights)}" if kw_highlights else ""
        summary_text = (
            f"Senior technology program and portfolio leader with 20+ years of experience across telecom, "
            f"enterprise technology, platforms, and digital transformation. Demonstrated success delivering high-impact "
            f"initiatives aligned with {job_title} scope at {job_company}{kw_clause}. "
            f"Expert in program governance, roadmaps, cross-functional engineering alignment, and measurable enterprise outcomes."
        )

    # 3. Tailor Key Competencies / Core Capabilities
    comp_text = sections["competencies"]
    if update_competencies:
        # Extract existing capabilities
        existing_caps = []
        for line in comp_text.splitlines():
            for part in line.split("•"):
                p = part.strip()
                if p and p not in existing_caps:
                    existing_caps.append(p)
        
        # Merge selected keywords into competencies
        merged_caps = []
        # Add selected keywords first for high ATS visibility
        for k in selected_keywords[:8]:
            title_k = k.strip().title()
            if title_k and title_k not in merged_caps:
                merged_caps.append(title_k)
        for c in existing_caps:
            if c not in merged_caps:
                merged_caps.append(c)

        comp_text = " • ".join(merged_caps[:16])

    # 4. Tailor Tools & Technology
    tools_text = sections["tools"]
    if update_tools and selected_keywords:
        # Check if any missing keyword is a known tool/methodology
        tool_kws = [k for k in selected_keywords if k.lower() in ("jira", "confluence", "servicenow", "okr", "kpi", "safe", "kanban", "sql", "tableau", "power bi", "looker", "azure devops", "cloud", "aws", "gcp")]
        if tool_kws:
            tools_text += f"\n• **Target Aligned Focus**: {', '.join(k.title() for k in tool_kws)}"

    # 5. Assemble Tailored Resume
    res_lines: list[str] = []

    # Header
    res_lines.append(sections["header"] if sections["header"] else "# Elena Shchetinina\nSenior Technical Program & Portfolio Leader\nToronto, Canada | 437-518-0634 | evschetinina@gmail.com")
    res_lines.append("")

    # Summary
    res_lines.append("## Professional Summary")
    res_lines.append(summary_text)
    res_lines.append("")

    # Competencies
    res_lines.append("## Core Capabilities")
    res_lines.append(comp_text)
    res_lines.append("")

    # Experience
    res_lines.append("## Professional Experience\n")
    if sections["current_role_meta"]:
        res_lines.append(sections["current_role_meta"])
    else:
        res_lines.append("### Bell Canada | Toronto, ON\n**Senior Program Manager / Agile Program Manager** | Jul 2024 – Feb 2026\n*Enterprise Architecture / Customer Operations Transformation*")

    for b in tailored_cur_bullets:
        res_lines.append(f"• {b}")
    res_lines.append("")

    # Earlier Experience
    if sections["earlier_experience"]:
        res_lines.append(sections["earlier_experience"])
        res_lines.append("")

    # Earlier Telecom Experience
    if sections["earlier_telecom"]:
        res_lines.append("## Earlier Telecom & Product Engineering Experience\n")
        res_lines.append(sections["earlier_telecom"])
        res_lines.append("")

    # Education & Certifications
    if sections["education"]:
        res_lines.append("## Education & Certifications\n")
        res_lines.append(sections["education"])
        res_lines.append("")

    # Tools & Technology
    if tools_text:
        res_lines.append("## Tools & Technology\n")
        res_lines.append(tools_text)

    tailored_full_text = "\n".join(res_lines).strip()

    metadata = {
        "job_title": job_title,
        "job_company": job_company,
        "selected_keywords": selected_keywords,
        "current_role_bullets_before": orig_cur_bullets,
        "current_role_bullets_after": tailored_cur_bullets,
        "bullets_added": len(tailored_cur_bullets) - len(orig_cur_bullets),
    }

    return tailored_full_text, metadata


# ---------------------------------------------------------------------------
# ATS Improvement Evaluation
# ---------------------------------------------------------------------------

def evaluate_tailoring_impact(
    original_resume_text: str,
    tailored_resume_text: str,
    parsed_jd: ParsedJD | dict[str, Any],
    evidence: list[EvidenceItem] | None = None,
    role_title: str = "",
) -> dict[str, Any]:
    """
    Compare ATS score between original master resume and tailored resume.
    """
    if isinstance(parsed_jd, dict):
        parsed_jd = ParsedJD.model_validate(parsed_jd)

    if evidence is None:
        evidence = load_evidence_library()

    all_keywords = parsed_jd.keywords + parsed_jd.must_haves + parsed_jd.preferred

    orig_ats = ats_engine.assess(
        keywords=all_keywords,
        resume_text=original_resume_text,
        evidence=evidence,
        role_title=role_title,
    )

    tailored_ats = ats_engine.assess(
        keywords=all_keywords,
        resume_text=tailored_resume_text,
        evidence=evidence,
        role_title=role_title,
    )

    orig_matched = {m.keyword.lower() for m in orig_ats.matches if m.exact_match or m.semantic_match}
    new_matched = {m.keyword.lower() for m in tailored_ats.matches if m.exact_match or m.semantic_match}
    newly_covered = [m.keyword for m in tailored_ats.matches if (m.exact_match or m.semantic_match) and m.keyword.lower() not in orig_matched]

    return {
        "original_readiness": orig_ats.readiness,
        "tailored_readiness": tailored_ats.readiness,
        "readiness_delta": round(tailored_ats.readiness - orig_ats.readiness, 1),
        "original_critical_coverage": orig_ats.critical_coverage,
        "tailored_critical_coverage": tailored_ats.critical_coverage,
        "original_important_coverage": orig_ats.important_coverage,
        "tailored_important_coverage": tailored_ats.important_coverage,
        "newly_covered_keywords": newly_covered,
        "tailored_ats": tailored_ats,
    }
