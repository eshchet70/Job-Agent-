"""
Shared test fixtures for the Job Search Operating Agent test suite.
"""
import json
import pytest
from pathlib import Path

from app.models import DimensionScore, EvidenceItem, JobRecord, ParsedJD, Requirement


FIXTURES_DIR = Path(__file__).parent


@pytest.fixture
def sample_jobs() -> list[dict]:
    with open(FIXTURES_DIR / "fixtures" / "sample_jobs.json") as fh:
        return json.load(fh)


@pytest.fixture
def sample_evidence() -> list[EvidenceItem]:
    """Load the real evidence library for integration tests."""
    with open("data/evidence_library.json") as fh:
        raw = json.load(fh)
    return [EvidenceItem.model_validate(item) for item in raw]


@pytest.fixture
def minimal_scores() -> dict[str, DimensionScore]:
    keys = ["functional", "seniority", "domain", "evidence",
            "location_auth", "competitive", "relationship"]
    return {k: DimensionScore(score=75, rationale="test") for k in keys}


@pytest.fixture
def tier1_scores() -> dict[str, DimensionScore]:
    keys = ["functional", "seniority", "domain", "evidence",
            "location_auth", "competitive", "relationship"]
    return {k: DimensionScore(score=88, rationale="strong match") for k in keys}


@pytest.fixture
def no_pursue_scores() -> dict[str, DimensionScore]:
    keys = ["functional", "seniority", "domain", "evidence",
            "location_auth", "competitive", "relationship"]
    return {k: DimensionScore(score=40, rationale="weak match") for k in keys}


@pytest.fixture
def sample_job() -> JobRecord:
    return JobRecord(
        company="Telus",
        title="Senior Technical Program Manager",
        description=(
            "Lead cross-functional technical programs. Must have 8+ years technical program "
            "management experience. Required: Agile, SAFe, portfolio governance, roadmap planning, "
            "stakeholder management, risk management, capacity planning. "
            "SAFe Lean Portfolio Management certification preferred. MBA preferred. "
            "Work authorization: Must be eligible to work in Canada."
        ),
        location="Toronto, ON",
        country="Canada",
    )


@pytest.fixture
def us_only_job() -> JobRecord:
    return JobRecord(
        company="Acme Corp",
        title="Senior Program Manager",
        description=(
            "Must be authorized to work in the United States. "
            "No visa sponsorship available for this position."
        ),
        location="Seattle, WA",
        country="United States",
    )


@pytest.fixture
def amazon_job() -> JobRecord:
    return JobRecord(
        company="Amazon",
        title="Senior TPM",
        description="Amazon is looking for a Senior TPM.",
        location="Toronto",
    )


@pytest.fixture
def cgi_job() -> JobRecord:
    return JobRecord(
        company="CGI",
        title="Senior Program Manager",
        description="CGI is looking for an experienced program manager.",
        location="Ottawa",
    )


@pytest.fixture
def hands_on_eng_job() -> JobRecord:
    return JobRecord(
        company="Startup Inc",
        title="Staff Software Engineer",
        description=(
            "You will write code daily. Hands-on coding required. "
            "You will hands-on code in Python and Go."
        ),
        location="Toronto",
    )


@pytest.fixture
def parsed_tpm_jd() -> ParsedJD:
    return ParsedJD(
        role_family="Technical Program Manager",
        seniority="Senior",
        must_haves=[
            Requirement(text="technical program management", importance="critical", category="core"),
            Requirement(text="stakeholder management", importance="critical", category="core"),
            Requirement(text="risk management", importance="critical", category="core"),
            Requirement(text="Agile", importance="important", category="technical"),
            Requirement(text="SAFe", importance="important", category="technical"),
        ],
        preferred=[
            Requirement(text="MBA", importance="supporting", category="education"),
            Requirement(text="ServiceNow", importance="supporting", category="technical"),
        ],
        keywords=[
            Requirement(text="Agile", importance="important", category="technical"),
            Requirement(text="SAFe", importance="important", category="technical"),
        ],
        location_auth_clues=[],
    )


# ---------------------------------------------------------------------------
# In-memory (isolated) database fixture for integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_db(monkeypatch, tmp_path):
    """
    Redirect the database to a fresh isolated SQLite file for each test.
    Patches engine, SessionLocal, and settings.database_url.
    """
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.db import database as db_mod
    from app.db.database import Base
    from app import config as cfg

    db_path = tmp_path / "test_job_search.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(cfg.settings, "database_url", db_url)

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(test_engine, "connect")
    def _set_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_mod, "engine", test_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSession)

    # Also patch the module-level get_session used throughout repository
    monkeypatch.setattr(db_mod, "get_session", lambda: TestSession())

    return test_engine
