"""
Database Layer
SQLAlchemy models and engine configuration
Designed for SQLite (MVP) with easy PostgreSQL migration path
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    create_engine, Column, String, Float, Integer,
    DateTime, Text, Boolean, JSON, ForeignKey,
)
from sqlalchemy.orm import sessionmaker, relationship, Session, declarative_base
from sqlalchemy.engine import Engine

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

Base = declarative_base()


# ── ORM Models ────────────────────────────────────────────────────────────────

class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: f"job_{uuid.uuid4().hex[:12]}")
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    parsed_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analyses = relationship("AnalysisRecord", back_populates="job")


class ResumeRecord(Base):
    __tablename__ = "resumes"

    id = Column(String, primary_key=True, default=lambda: f"res_{uuid.uuid4().hex[:12]}")
    filename = Column(String, nullable=False)
    candidate_name = Column(String, default="Unknown")
    email = Column(String, default="")
    phone = Column(String, default="")
    parsed_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # NOTE: Resume files are NOT stored — only metadata and parsed data


class AnalysisRecord(Base):
    __tablename__ = "analyses"

    id = Column(String, primary_key=True, default=lambda: f"ana_{uuid.uuid4().hex[:12]}")
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    resume_id = Column(String, ForeignKey("resumes.id"), nullable=False)
    candidate_name = Column(String, default="")
    overall_score = Column(Float, default=0.0)
    recommendation = Column(String, default="")
    section_scores = Column(JSON, nullable=True)
    skill_match = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    gaps = Column(JSON, nullable=True)
    llm_insights = Column(Text, nullable=True)
    batch_id = Column(String, nullable=True)
    rank = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobRecord", back_populates="analyses")


class BatchRecord(Base):
    __tablename__ = "batches"

    id = Column(String, primary_key=True, default=lambda: f"bat_{uuid.uuid4().hex[:12]}")
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    total_candidates = Column(Integer, default=0)
    chart_paths = Column(JSON, nullable=True)
    comparison_table = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationStateRecord(Base):
    __tablename__ = "conversation_states"

    id = Column(String, primary_key=True)  # platform:user_id
    platform = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    state = Column(String, default="idle")
    job_id = Column(String, nullable=True)
    resume_ids = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Engine & Session ──────────────────────────────────────────────────────────

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        import os
        os.makedirs("data", exist_ok=True)
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},  # SQLite specific
            echo=settings.debug,
        )
        logger.info(f"Database engine created: {settings.database_url}")
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_db() -> Session:
    """FastAPI dependency: yield a database session."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized.")
