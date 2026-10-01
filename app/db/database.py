"""
SQLAlchemy 2.0 ORM models and database engine for the Job Search Operating Agent.
System of record: SQLite at data/job_search.db
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
    create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session, sessionmaker

from app.config import settings


# ---------------------------------------------------------------------------
# Engine & Session factory
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Ensure WAL mode for better concurrency
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing."""
    return SessionLocal()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class JobDB(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company = Column(String, nullable=False)
    title = Column(String, nullable=False)
    job_id = Column(String, nullable=True)
    official_url = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    source_type = Column(String, nullable=True)      # "official_career","indeed","linkedin","manual",...
    location = Column(String, nullable=True)
    country = Column(String, nullable=True)
    work_model = Column(String, nullable=True)
    posted_date = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    status = Column(String, default="UNKNOWN")
    description = Column(Text, nullable=False)
    role_family = Column(String, nullable=True)
    seniority = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    gate_result = relationship("HardGateDB", back_populates="job", uselist=False,
                               cascade="all, delete-orphan")
    strategic_fit = relationship("StrategicFitDB", back_populates="job", uselist=False,
                                 cascade="all, delete-orphan")
    ats_assessment = relationship("ATSAssessmentDB", back_populates="job", uselist=False,
                                  cascade="all, delete-orphan")
    people = relationship("PersonDB", back_populates="job", cascade="all, delete-orphan")
    outreach_records = relationship("OutreachDB", back_populates="job",
                                    cascade="all, delete-orphan")
    application = relationship("ApplicationDB", back_populates="job", uselist=False,
                               cascade="all, delete-orphan")


class HardGateDB(Base):
    __tablename__ = "hard_gates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    passed = Column(Boolean, default=True)
    barriers_json = Column(Text, default="[]")       # JSON list
    authorization_status = Column(String, nullable=True)
    location_status = Column(String, nullable=True)
    profession_match = Column(String, nullable=True)
    mandatory_credential_status = Column(String, nullable=True)
    company_exclusion = Column(String, nullable=True)
    evaluated_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobDB", back_populates="gate_result")

    @property
    def barriers(self) -> list[str]:
        return json.loads(self.barriers_json or "[]")

    @barriers.setter
    def barriers(self, value: list[str]):
        self.barriers_json = json.dumps(value)


class StrategicFitDB(Base):
    __tablename__ = "strategic_fits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    functional_score = Column(Integer)
    seniority_score = Column(Integer)
    domain_score = Column(Integer)
    evidence_score = Column(Integer)
    location_auth_score = Column(Integer)
    competitive_score = Column(Integer)
    relationship_score = Column(Integer)
    weighted_score = Column(Float)
    tier = Column(String)
    dimensions_json = Column(Text, default="{}")   # full JSON blob
    barriers_json = Column(Text, default="[]")
    calculated_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobDB", back_populates="strategic_fit")


class ATSAssessmentDB(Base):
    __tablename__ = "ats_assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    readiness = Column(Float)
    critical_coverage = Column(Float)
    important_coverage = Column(Float)
    evidence_coverage = Column(Float)
    placement_score = Column(Float, default=0.0)
    role_alignment_score = Column(Float, default=0.0)
    matches_json = Column(Text, default="[]")      # full JSON blob
    resume_version = Column(String, nullable=True)
    assessed_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobDB", back_populates="ats_assessment")


class PersonDB(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    name = Column(String, nullable=False)
    current_title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    person_type = Column(String, nullable=False)
    relationship_to_job = Column(String, nullable=False)
    relationship_status = Column(String, default="inferred")
    confidence = Column(String)
    source_url = Column(String, nullable=True)
    source_summary = Column(String, nullable=True)
    checked_at = Column(DateTime, nullable=True)
    connection_path = Column(String, nullable=True)
    outreach_priority = Column(Integer, default=99)
    message_objective = Column(String, nullable=True)
    draft_message = Column(Text, nullable=True)
    channel = Column(String, nullable=True)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobDB", back_populates="people")
    outreach_records = relationship("OutreachDB", back_populates="person",
                                    cascade="all, delete-orphan")


class OutreachDB(Base):
    __tablename__ = "outreach"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=True)
    person_name = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    objective = Column(String, nullable=True)
    draft = Column(Text, nullable=True)
    evidence_ids_json = Column(Text, default="[]")
    approval_status = Column(String, default="pending")
    contacted_at = Column(DateTime, nullable=True)
    response = Column(Text, nullable=True)
    next_action = Column(String, nullable=True)
    next_action_date = Column(String, nullable=True)
    recipient_email = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobDB", back_populates="outreach_records")
    person = relationship("PersonDB", back_populates="outreach_records")


class ApplicationDB(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    applied_at = Column(DateTime, nullable=True)
    resume_version = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    status = Column(String, default="draft")
    status_source = Column(String, nullable=True)
    status_checked_at = Column(DateTime, nullable=True)
    next_action = Column(String, nullable=True)
    next_action_date = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobDB", back_populates="application")


class SyncConflictDB(Base):
    __tablename__ = "sync_conflicts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False)         # "mygreenhouse", "indeed", "linkedin"
    external_id = Column(String, nullable=False)
    local_record_id = Column(Integer, nullable=True)
    field = Column(String, nullable=False)
    local_value = Column(Text, nullable=True)
    provider_value = Column(Text, nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolution_status = Column(String, default="pending")
    resolution_note = Column(Text, nullable=True)


class AuditLogDB(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Bootstrap — create all tables
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they do not exist and ensure columns exist. Safe to call on every startup."""
    import os
    import sqlite3
    # Ensure the data directory exists
    db_path = settings.database_url.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # Safe column migrations for existing SQLite databases
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(people)")
            p_cols = {col[1] for col in cur.fetchall()}
            if "email" not in p_cols:
                cur.execute("ALTER TABLE people ADD COLUMN email VARCHAR")

            cur.execute("PRAGMA table_info(outreach)")
            o_cols = {col[1] for col in cur.fetchall()}
            if "recipient_email" not in o_cols:
                cur.execute("ALTER TABLE outreach ADD COLUMN recipient_email VARCHAR")
            if "subject" not in o_cols:
                cur.execute("ALTER TABLE outreach ADD COLUMN subject VARCHAR")
            conn.commit()
            conn.close()
        except Exception:
            pass
