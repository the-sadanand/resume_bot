"""
Job Description Routes
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.models.job import JobCreateRequest, JobResponse, ParsedJobDescription
from app.services.jd_parser import parse_job_description
from app.storage.database import get_db
from app.storage.repositories import JobRepository

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])
logger = logging.getLogger(__name__)


@router.post("", response_model=JobResponse)
async def create_job(
    request: JobCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Submit a Job Description for parsing.
    Returns a job_id to use in screening requests.
    """
    # Parse the JD
    parsed = parse_job_description(request.description, provided_title=request.title)

    # Generate ID
    job_id = f"job_{uuid.uuid4().hex[:12]}"

    # Store
    repo = JobRepository(db)
    repo.create(
        job_id=job_id,
        title=request.title,
        description=request.description,
        parsed_data=parsed.model_dump(),
    )

    logger.info(
        f"Job created: {job_id}, title: {request.title}, "
        f"required_skills: {len(parsed.required_skills)}"
    )

    return JobResponse(
        job_id=job_id,
        title=request.title,
        parsed=parsed,
        status="created",
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve a job description by ID."""
    repo = JobRepository(db)
    record = repo.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    parsed = ParsedJobDescription(**record.parsed_data)
    return JobResponse(
        job_id=record.id,
        title=record.title,
        parsed=parsed,
        status="ok",
    )


@router.get("")
async def list_jobs(db: Session = Depends(get_db)):
    """List all job descriptions."""
    repo = JobRepository(db)
    records = repo.list_all()
    return [
        {"job_id": r.id, "title": r.title, "created_at": r.created_at.isoformat()}
        for r in records
    ]
