"""
Shared test job fixtures — 10 deterministic JD scenarios.
Import this module directly for parametrized tests.
"""
from __future__ import annotations

JOBS: list[dict] = [
    {
        "id": "tpm_shopify",
        "company": "Shopify",
        "title": "Senior Technical Program Manager",
        "location": "Toronto, ON (Remote)",
        "country": "CA",
        "work_model": "remote",
        "jd": (
            "Shopify is looking for a Senior Technical Program Manager to lead cross-functional "
            "delivery across our platform modernization programs. You will own roadmap planning, "
            "risk management, dependency management, stakeholder management and executive reporting. "
            "Experience with Agile, SAFe and capacity planning required. Experience with AI and "
            "cloud modernization preferred. Toronto or remote."
        ),
    },
    {
        "id": "portfolio_mgr_rbc",
        "company": "RBC",
        "title": "Director, Technology Portfolio Management",
        "location": "Toronto, ON",
        "country": "CA",
        "work_model": "hybrid",
        "jd": (
            "RBC Technology is seeking a Director of Technology Portfolio Management. You will lead "
            "governance, intake, LPM and planning cycles across a large portfolio. Strong experience "
            "with portfolio management, roadmap, Agile delivery, executive stakeholder management, "
            "financial management and vendor governance required."
        ),
    },
    {
        "id": "ai_program_google",
        "company": "Google",
        "title": "AI Program Manager, Cloud",
        "location": "Waterloo, ON (Hybrid)",
        "country": "CA",
        "work_model": "hybrid",
        "jd": (
            "We are looking for an AI Program Manager to lead AI and machine learning platform "
            "programs across Google Cloud. Responsibilities include stakeholder management, "
            "roadmap planning, cross-functional delivery, risk management and executive reporting. "
            "Experience with AI, data platform and cloud modernization required."
        ),
    },
    {
        "id": "excluded_amazon",
        "company": "Amazon",
        "title": "Senior Program Manager",
        "location": "Seattle, WA",
        "country": "US",
        "work_model": "on-site",
        "jd": (
            "Amazon Stores is looking for a Senior Program Manager. Must be authorized to work "
            "in the United States. No sponsorship available. Stakeholder management, roadmap "
            "and Agile required."
        ),
    },
    {
        "id": "excluded_cgi",
        "company": "CGI",
        "title": "Technical Program Manager",
        "location": "Ottawa, ON",
        "country": "CA",
        "work_model": "hybrid",
        "jd": (
            "CGI is hiring a Technical Program Manager for government programs. "
            "Agile, stakeholder management, and delivery management required."
        ),
    },
    {
        "id": "us_no_sponsorship",
        "company": "Salesforce",
        "title": "Principal Technical Program Manager",
        "location": "San Francisco, CA",
        "country": "US",
        "work_model": "hybrid",
        "jd": (
            "Principal Technical Program Manager at Salesforce. Must be authorized to work in "
            "the United States. No visa sponsorship. Strong technical program management, "
            "portfolio management, risk management and stakeholder management required."
        ),
    },
    {
        "id": "swe_mismatch",
        "company": "Meta",
        "title": "Software Development Engineer",
        "location": "Toronto, ON",
        "country": "CA",
        "work_model": "hybrid",
        "jd": (
            "Meta is hiring a hands-on software engineer for our infrastructure team. "
            "You will write production code, design systems, and ship features. "
            "Deep hands-on software engineering required."
        ),
    },
    {
        "id": "tpm_telus",
        "company": "Telus",
        "title": "Senior Program Manager, Technology Transformation",
        "location": "Vancouver, BC (Remote)",
        "country": "CA",
        "work_model": "remote",
        "jd": (
            "Telus is seeking a Senior Program Manager to lead technology transformation and "
            "platform modernization programs. Agile, roadmap planning, risk management, "
            "stakeholder management, vendor governance required. AI and cloud experience preferred."
        ),
    },
    {
        "id": "portfolio_bmo",
        "company": "BMO",
        "title": "Portfolio Manager, Digital Technology",
        "location": "Toronto, ON",
        "country": "CA",
        "work_model": "hybrid",
        "jd": (
            "BMO is looking for a Portfolio Manager in Digital Technology. Lead intake, "
            "governance, roadmap, capacity planning and executive stakeholder management. "
            "LPM, Agile and SAFe required. ServiceNow experience is a plus."
        ),
    },
    {
        "id": "tpm_microsoft",
        "company": "Microsoft",
        "title": "Principal Program Manager, Azure",
        "location": "Redmond, WA (Remote eligible)",
        "country": "US",
        "work_model": "remote",
        "jd": (
            "Microsoft Azure is looking for a Principal Program Manager. Lead cross-functional "
            "delivery, roadmap planning, dependency management, stakeholder management and "
            "executive reporting across cloud platform programs. Agile, AI and cloud required. "
            "Remote eligible — Canada candidates welcome."
        ),
    },
]
