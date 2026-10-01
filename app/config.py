"""
App configuration using pydantic-settings.
All values read from environment / .env file; none hard-wired.
"""
from __future__ import annotations

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///data/job_search.db"

    # Excel tracker
    tracker_path: str = "data/tracker_template.xlsx"

    # Candidate data
    candidate_profile_path: str = "data/candidate_profile.json"
    evidence_library_path: str = "data/evidence_library.json"

    # LLM / model provider (optional; deterministic engines work without it)
    model_provider: str = "none"       # "openai" | "gemini" | "none"
    model_name: str = "gpt-4o"
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # ATS fuzzy-match threshold (0–100; lower → more semantic matches)
    ats_fuzzy_threshold: int = 82

    # Job portal settings
    indeed_rss_base: str = "https://www.indeed.com/rss"
    indeed_search_base: str = "https://ca.indeed.com"
    linkedin_search_base: str = "https://www.linkedin.com/jobs/search"
    glassdoor_search_base: str = "https://www.glassdoor.ca/Job"

    # SMTP Email settings
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender_email: str = ""
    smtp_sender_name: str = "Elena Shchetinina"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
