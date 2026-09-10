"""
Resume Upload Routes
"""
import uuid
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from app.models.resume import ResumeUploadResponse
from app.services.resume_parser import parse_resume
from app.utils.file_utils import (
    validate_file_extension, validate_file_size,
    save_temp_file, delete_temp_file, get_safe_filename,
)
from app.storage.database import get_db
from app.storage.repositories import ResumeRepository
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1/resumes", tags=["Resumes"])
logger = logging.getLogger(__name__)
settings = get_settings()


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a resume file (PDF or DOCX).
    The file is parsed and metadata stored; the raw file is deleted after parsing.
    Privacy: Resume content is never logged.
    """
    filename = get_safe_filename(file.filename or "resume.pdf")

    # Validate extension
    if not validate_file_extension(filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions}"
        )

    # Read file
    file_bytes = await file.read()

    # Validate size
    if not validate_file_size(file_bytes):
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum: {settings.max_file_size_mb}MB"
        )

    # Save temp file
    temp_path = save_temp_file(file_bytes, filename)

    try:
        # Parse resume
        parsed = parse_resume(temp_path)

        # Generate ID
        resume_id = f"res_{uuid.uuid4().hex[:12]}"

        # Store metadata (not raw file)
        repo = ResumeRepository(db)
        repo.create(
            resume_id=resume_id,
            filename=filename,
            candidate_name=parsed.name,
            email=parsed.email,
            phone=parsed.phone,
            parsed_data=parsed.model_dump(exclude={"raw_text"}),  # Don't store raw text in DB
        )

        logger.info(f"Resume uploaded: {resume_id}, candidate: {parsed.name}")

        return ResumeUploadResponse(
            resume_id=resume_id,
            filename=filename,
            candidate_name=parsed.name,
            status="parsed",
            message=f"Resume parsed successfully. Found {len(parsed.skills)} skills.",
        )

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Resume upload failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to process resume")
    finally:
        # Always delete temp file — privacy
        delete_temp_file(temp_path)


@router.post("/upload-multiple")
async def upload_multiple_resumes(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload multiple resume files at once."""
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 resumes at a time")

    results = []
    for file in files:
        filename = get_safe_filename(file.filename or "resume.pdf")
        if not validate_file_extension(filename):
            results.append({"filename": filename, "status": "error", "message": "Unsupported file type"})
            continue

        file_bytes = await file.read()
        if not validate_file_size(file_bytes):
            results.append({"filename": filename, "status": "error", "message": "File too large"})
            continue

        temp_path = save_temp_file(file_bytes, filename)
        try:
            parsed = parse_resume(temp_path)
            resume_id = f"res_{uuid.uuid4().hex[:12]}"
            repo = ResumeRepository(db)
            repo.create(
                resume_id=resume_id,
                filename=filename,
                candidate_name=parsed.name,
                email=parsed.email,
                phone=parsed.phone,
                parsed_data=parsed.model_dump(exclude={"raw_text"}),
            )
            results.append({
                "filename": filename,
                "resume_id": resume_id,
                "candidate_name": parsed.name,
                "status": "parsed",
                "skills_count": len(parsed.skills),
            })
        except Exception as e:
            logger.error(f"Failed to parse {filename}: {type(e).__name__}")
            results.append({"filename": filename, "status": "error", "message": "Parse failed"})
        finally:
            delete_temp_file(temp_path)

    return {"uploaded": len(results), "results": results}
