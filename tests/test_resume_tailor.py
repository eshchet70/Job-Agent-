"""
Tests for app.services.resume_tailor.
"""
from __future__ import annotations

from app.models import JobRecord, ParsedJD, Requirement
from app.services import resume_tailor
from app.services.evidence_loader import load_evidence_library


SAMPLE_RESUME = """# Elena Shchetinina
Senior Technical Program & Portfolio Leader | Platforms, Data, AI & Enterprise Transformation
Toronto, Canada  |  437-518-0634  |  evschetinina@gmail.com

## Professional Summary
Senior technical program and portfolio leader with 20+ years of experience across telecom, e-commerce, enterprise platforms, data and public-sector transformation.

## Core Capabilities
Technical Program Management • Portfolio Governance • Platform & Data Programs • Roadmaps • Agile / SAFe

## Professional Experience

### Bell Canada | Toronto, ON
**Senior Program Manager / Agile Program Manager** | Jul 2024 – Feb 2026  
*Enterprise Architecture / Customer Operations Transformation*
• Across a ~1,400-application portfolio where technology costs were fragmented across multiple systems, led Bell-side TCO data collection and stakeholder coordination with KPMG, validating the methodology on ~300 applications.
• As Bell pursued $60M in cost reduction by replacing a legacy payment application with a new technology stack, led program execution for a six-person Enterprise Architecture team.
• To replace legacy customer-profile functionality and reduce ongoing support costs by several million dollars, coordinated architecture, development and SaaS/platform teams.

### Amazon | New York, NY
**Senior Program Manager, Hardlines / Catalog Data** | Feb 2022 – Apr 2023  
*Marketplace Product Data, Ontology & Catalog Programs*
• Managed Hardlines schema review and automation with Engineering.

## Earlier Telecom & Product Engineering Experience

### MegaFon Moscow & Beeline / VimpelCom | Moscow, Russia
**Billing & OSS/BSS Integrations** | 1999 – 2003
• Developed billing and OSS/BSS integrations.

## Education & Certifications
• **MBA** — Rotman School of Management, University of Toronto
• **B.S., Computer Information Systems** — University of Northern Colorado

## Tools & Technology
• **Program & Delivery**: Jira, Confluence, Asana, Agile, SAFe
• **Platforms & Architecture**: ServiceNow, Salesforce
"""


def test_parse_resume_sections():
    sections = resume_tailor.parse_resume_sections(SAMPLE_RESUME)
    assert "Elena Shchetinina" in sections["header"]
    assert "Senior technical program and portfolio leader" in sections["summary"]
    assert "Technical Program Management" in sections["competencies"]
    assert "Bell Canada" in sections["current_role_meta"]
    assert len(sections["current_role_bullets"]) == 3
    assert "1,400-application" in sections["current_role_bullets"][0]
    assert "Amazon" in sections["earlier_experience"]
    assert "MegaFon" in sections["earlier_telecom"]
    assert "Rotman" in sections["education"]
    assert "ServiceNow" in sections["tools"]


def test_detect_missing_keywords():
    parsed_jd = ParsedJD(
        keywords=[
            Requirement(text="technical program management", importance="critical", category="core"),
            Requirement(text="cloud modernization", importance="important", category="domain"),
            Requirement(text="vendor governance", importance="important", category="governance"),
            Requirement(text="capacity planning", importance="critical", category="planning"),
        ],
        must_haves=[],
        preferred=[],
        seniority="Senior",
        role_family="TPM",
    )

    result = resume_tailor.detect_missing_keywords(parsed_jd, SAMPLE_RESUME)
    missing_resume_kws = [m["keyword"] for m in result["missing_from_resume"]]
    missing_cur_kws = [m["keyword"] for m in result["missing_from_current_role"]]

    assert "cloud modernization" in missing_resume_kws
    assert "vendor governance" in missing_resume_kws
    assert "capacity planning" in missing_resume_kws
    assert "cloud modernization" in missing_cur_kws


def test_generate_tailored_current_role_bullets():
    existing = [
        "Across a ~1,400-application portfolio where technology costs were fragmented across multiple systems, led Bell-side TCO data collection and stakeholder coordination with KPMG.",
        "As Bell pursued $60M in cost reduction by replacing a legacy payment application with a new technology stack, led program execution for a six-person Enterprise Architecture team.",
        "To replace legacy customer-profile functionality and reduce ongoing support costs by several million dollars, coordinated architecture, development and SaaS/platform teams.",
    ]

    missing = ["cloud modernization", "vendor governance", "capacity planning", "ServiceNow"]
    updated = resume_tailor.generate_tailored_current_role_bullets(
        missing_keywords=missing,
        existing_bullets=existing,
        job_title="Director, Enterprise Program Delivery",
        company="Bell Canada",
    )

    assert len(updated) >= 3
    joined = " ".join(updated).lower()
    # Check that missing keywords were integrated
    assert "servicenow" in joined
    assert "vendor governance" in joined or "governance" in joined
    assert "cloud" in joined


def test_tailor_resume_full():
    job = JobRecord(
        company="Bank of Montreal (BMO)",
        title="Director, Enterprise Program Delivery",
        description="Lead enterprise programs, cloud modernization, vendor governance, capacity planning.",
    )
    parsed_jd = ParsedJD(
        keywords=[
            Requirement(text="cloud modernization", importance="critical", category="domain"),
            Requirement(text="vendor governance", importance="important", category="governance"),
            Requirement(text="capacity planning", importance="critical", category="planning"),
        ],
        must_haves=[],
        preferred=[],
        seniority="Director",
        role_family="TPM",
    )

    tailored_text, metadata = resume_tailor.tailor_resume(
        master_resume_text=SAMPLE_RESUME,
        job=job,
        parsed_jd=parsed_jd,
        selected_keywords=["cloud modernization", "vendor governance", "capacity planning"],
        update_current_role=True,
        update_summary=True,
        update_competencies=True,
    )

    assert "Bank of Montreal (BMO)" in tailored_text
    assert "Director, Enterprise Program Delivery" in tailored_text
    assert "Cloud Modernization" in tailored_text or "cloud modernization" in tailored_text
    assert "Vendor Governance" in tailored_text or "vendor governance" in tailored_text
    assert "Capacity Planning" in tailored_text or "capacity planning" in tailored_text
    # Verify reverse-chronological order preserved
    bell_pos = tailored_text.find("Bell Canada")
    amazon_pos = tailored_text.find("Amazon")
    edu_pos = tailored_text.find("Education & Certifications")
    assert bell_pos < amazon_pos < edu_pos


def test_evaluate_tailoring_impact():
    parsed_jd = ParsedJD(
        keywords=[
            Requirement(text="technical program management", importance="critical", category="core"),
            Requirement(text="cloud modernization", importance="critical", category="domain"),
            Requirement(text="vendor governance", importance="important", category="governance"),
        ],
        must_haves=[],
        preferred=[],
        seniority="Senior",
        role_family="TPM",
    )
    job = JobRecord(
        company="BMO",
        title="Senior Technical Program Manager",
        description="...",
    )

    tailored_text, _ = resume_tailor.tailor_resume(
        master_resume_text=SAMPLE_RESUME,
        job=job,
        parsed_jd=parsed_jd,
        selected_keywords=["cloud modernization", "vendor governance"],
    )

    impact = resume_tailor.evaluate_tailoring_impact(
        original_resume_text=SAMPLE_RESUME,
        tailored_resume_text=tailored_text,
        parsed_jd=parsed_jd,
        role_title="Senior Technical Program Manager",
    )

    assert impact["tailored_readiness"] >= impact["original_readiness"]
    assert impact["tailored_critical_coverage"] >= impact["original_critical_coverage"]
