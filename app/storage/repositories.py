"""
Repository Layer
Data access objects for all database entities
"""
import logging
from typing import Optional, List
from sqlalchemy.orm import Session

from app.storage.database import (
    JobRecord, ResumeRecord, AnalysisRecord, BatchRecord, ConversationStateRecord
)

logger = logging.getLogger(__name__)


class JobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, job_id: str, title: str, description: str, parsed_data: dict) -> JobRecord:
        record = JobRecord(
            id=job_id,
            title=title,
            description=description,
            parsed_data=parsed_data,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        return self.db.query(JobRecord).filter(JobRecord.id == job_id).first()

    def list_all(self) -> List[JobRecord]:
        return self.db.query(JobRecord).order_by(JobRecord.created_at.desc()).all()


class ResumeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        resume_id: str,
        filename: str,
        candidate_name: str,
        email: str,
        phone: str,
        parsed_data: dict,
    ) -> ResumeRecord:
        record = ResumeRecord(
            id=resume_id,
            filename=filename,
            candidate_name=candidate_name,
            email=email,
            phone=phone,
            parsed_data=parsed_data,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get(self, resume_id: str) -> Optional[ResumeRecord]:
        return self.db.query(ResumeRecord).filter(ResumeRecord.id == resume_id).first()

    def get_many(self, resume_ids: List[str]) -> List[ResumeRecord]:
        return self.db.query(ResumeRecord).filter(ResumeRecord.id.in_(resume_ids)).all()


class AnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        analysis_id: str,
        job_id: str,
        resume_id: str,
        candidate_name: str,
        overall_score: float,
        recommendation: str,
        section_scores: dict,
        skill_match: dict,
        strengths: list,
        gaps: list,
        llm_insights: Optional[str] = None,
        batch_id: Optional[str] = None,
        rank: Optional[int] = None,
    ) -> AnalysisRecord:
        record = AnalysisRecord(
            id=analysis_id,
            job_id=job_id,
            resume_id=resume_id,
            candidate_name=candidate_name,
            overall_score=overall_score,
            recommendation=recommendation,
            section_scores=section_scores,
            skill_match=skill_match,
            strengths=strengths,
            gaps=gaps,
            llm_insights=llm_insights,
            batch_id=batch_id,
            rank=rank,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get(self, analysis_id: str) -> Optional[AnalysisRecord]:
        return self.db.query(AnalysisRecord).filter(AnalysisRecord.id == analysis_id).first()

    def get_by_batch(self, batch_id: str) -> List[AnalysisRecord]:
        return (
            self.db.query(AnalysisRecord)
            .filter(AnalysisRecord.batch_id == batch_id)
            .order_by(AnalysisRecord.rank)
            .all()
        )


class BatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        batch_id: str,
        job_id: str,
        total_candidates: int,
        chart_paths: list,
        comparison_table: list,
    ) -> BatchRecord:
        record = BatchRecord(
            id=batch_id,
            job_id=job_id,
            total_candidates=total_candidates,
            chart_paths=chart_paths,
            comparison_table=comparison_table,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get(self, batch_id: str) -> Optional[BatchRecord]:
        return self.db.query(BatchRecord).filter(BatchRecord.id == batch_id).first()


class ConversationStateRepository:
    def __init__(self, db: Session):
        self.db = db

    def _make_id(self, platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}"

    def get_or_create(self, platform: str, user_id: str) -> ConversationStateRecord:
        state_id = self._make_id(platform, user_id)
        record = self.db.query(ConversationStateRecord).filter(
            ConversationStateRecord.id == state_id
        ).first()
        if not record:
            record = ConversationStateRecord(
                id=state_id,
                platform=platform,
                user_id=user_id,
                state="idle",
                resume_ids=[],
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        return record

    def update(self, platform: str, user_id: str, **kwargs) -> ConversationStateRecord:
        record = self.get_or_create(platform, user_id)
        for key, value in kwargs.items():
            setattr(record, key, value)
        self.db.commit()
        self.db.refresh(record)
        return record

    def reset(self, platform: str, user_id: str) -> None:
        record = self.get_or_create(platform, user_id)
        record.state = "idle"
        record.job_id = None
        record.resume_ids = []
        self.db.commit()
