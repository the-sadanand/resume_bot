"""
Screening Routes
Single and batch resume screening endpoints
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.models.screening import (
    ScreenRequest, BatchScreenRequest,
    ScreeningResult, BatchScreeningResult,
    SectionScores, SkillMatchDetail, RankedCandidate,
)
from app.models.resume import ParsedResume
from app.models.job import ParsedJobDescription
from app.services.scoring_engine import screen_resume
from app.services.ranking_service import rank_candidates, build_comparison_table
from app.services.report_service import format_single_report, format_batch_report
from app.services.llm_service import get_llm_service
from app.utils.chart_utils import generate_overall_score_chart, generate_section_comparison_chart
from app.storage.database import get_db
from app.storage.repositories import (
    JobRepository, ResumeRepository, AnalysisRepository, BatchRepository
)
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["Screening"])
logger = logging.getLogger(__name__)
settings = get_settings()


def _load_job_and_resume(job_id: str, resume_id: str, db: Session):
    """Helper to load job and resume from DB."""
    job_repo = JobRepository(db)
    resume_repo = ResumeRepository(db)

    job_record = job_repo.get(job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    resume_record = resume_repo.get(resume_id)
    if not resume_record:
        raise HTTPException(status_code=404, detail=f"Resume not found: {resume_id}")

    jd = ParsedJobDescription(**job_record.parsed_data)
    # Reconstruct ParsedResume with raw_text as empty (not stored for privacy)
    parsed_data = resume_record.parsed_data or {}
    parsed_data["raw_text"] = ""  # Not stored
    resume = ParsedResume(**parsed_data)

    return jd, resume, job_record, resume_record


@router.post("/screen", response_model=ScreeningResult)
async def screen_single(
    request: ScreenRequest,
    db: Session = Depends(get_db),
):
    """
    Screen a single resume against a Job Description.
    Returns a full screening result with scores, matched skills, strengths, and gaps.
    """
    if len(request.resume_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="Use /screen/batch for multiple resumes. /screen takes exactly 1 resume_id."
        )

    resume_id = request.resume_ids[0]
    jd, resume, job_record, resume_record = _load_job_and_resume(request.job_id, resume_id, db)

    # Run screening
    section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)

    # Optional LLM insights
    llm_service = get_llm_service()
    llm_insights = None
    if llm_service.is_available():
        try:
            llm_insights = llm_service.generate_insights(
                candidate_name=resume.name,
                job_title=job_record.title,
                overall_score=overall_score,
                matched_skills=skill_detail.matched,
                missing_skills=skill_detail.missing,
                years_experience=resume.total_years_experience,
            )
        except Exception as e:
            logger.warning(f"LLM insights failed: {e}")

    recommendation = settings.get_score_category(overall_score)
    analysis_id = f"ana_{uuid.uuid4().hex[:12]}"

    # Store analysis
    analysis_repo = AnalysisRepository(db)
    analysis_repo.create(
        analysis_id=analysis_id,
        job_id=request.job_id,
        resume_id=resume_id,
        candidate_name=resume.name,
        overall_score=overall_score,
        recommendation=recommendation,
        section_scores=section_scores.model_dump(),
        skill_match=skill_detail.model_dump(),
        strengths=strengths,
        gaps=gaps,
        llm_insights=llm_insights,
    )

    logger.info(f"Screening complete: {analysis_id}, score: {overall_score}")

    return ScreeningResult(
        analysis_id=analysis_id,
        candidate_name=resume.name,
        overall_score=overall_score,
        recommendation=recommendation,
        section_scores=section_scores,
        skill_match=skill_detail,
        strengths=strengths,
        gaps=gaps,
        llm_insights=llm_insights,
    )


@router.post("/screen/batch", response_model=BatchScreeningResult)
async def screen_batch(
    request: BatchScreenRequest,
    db: Session = Depends(get_db),
):
    """
    Screen multiple resumes against a Job Description.
    Returns ranked results, comparison table, and chart paths.
    """
    if len(request.resume_ids) < 2:
        raise HTTPException(status_code=400, detail="Batch screening requires at least 2 resume_ids")

    job_repo = JobRepository(db)
    job_record = job_repo.get(request.job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")

    jd = ParsedJobDescription(**job_record.parsed_data)
    resume_repo = ResumeRepository(db)
    resume_records = resume_repo.get_many(request.resume_ids)

    if not resume_records:
        raise HTTPException(status_code=404, detail="No resumes found for provided IDs")

    batch_id = f"bat_{uuid.uuid4().hex[:12]}"
    candidate_results = []
    analysis_repo = AnalysisRepository(db)

    llm_service = get_llm_service()

    for resume_record in resume_records:
        parsed_data = resume_record.parsed_data or {}
        parsed_data["raw_text"] = ""
        resume = ParsedResume(**parsed_data)

        section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)

        llm_insights = None
        if llm_service.is_available():
            try:
                llm_insights = llm_service.generate_insights(
                    candidate_name=resume.name,
                    job_title=job_record.title,
                    overall_score=overall_score,
                    matched_skills=skill_detail.matched,
                    missing_skills=skill_detail.missing,
                    years_experience=resume.total_years_experience,
                )
            except Exception:
                pass

        recommendation = settings.get_score_category(overall_score)
        analysis_id = f"ana_{uuid.uuid4().hex[:12]}"

        analysis_repo.create(
            analysis_id=analysis_id,
            job_id=request.job_id,
            resume_id=resume_record.id,
            candidate_name=resume.name,
            overall_score=overall_score,
            recommendation=recommendation,
            section_scores=section_scores.model_dump(),
            skill_match=skill_detail.model_dump(),
            strengths=strengths,
            gaps=gaps,
            llm_insights=llm_insights,
            batch_id=batch_id,
        )

        candidate_results.append({
            "name": resume.name,
            "analysis_id": analysis_id,
            "overall_score": overall_score,
            "section_scores": section_scores,
            "skill_match": skill_detail,
            "resume": resume,
        })

    # Rank candidates
    ranked = rank_candidates(candidate_results)

    # Update ranks in DB
    for rc in ranked:
        record = analysis_repo.get(rc.analysis_id)
        if record:
            record.rank = rc.rank
            db.commit()

    comparison_table = build_comparison_table(ranked)

    # Generate charts
    chart_paths = []
    try:
        score_data = [{"name": rc.candidate_name, "score": rc.overall_score} for rc in ranked]
        score_chart = generate_overall_score_chart(score_data, job_record.title)
        chart_paths.append(score_chart)

        section_data = []
        for rc in ranked:
            section_data.append({
                "name": rc.candidate_name,
                "skills": rc.section_scores.skills,
                "experience": rc.section_scores.experience,
                "projects": rc.section_scores.projects,
                "education": rc.section_scores.education,
                "jd_match": rc.section_scores.jd_match,
            })
        comp_chart = generate_section_comparison_chart(section_data, job_record.title)
        chart_paths.append(comp_chart)
    except Exception as e:
        logger.warning(f"Chart generation failed: {e}")

    # Store batch record
    batch_repo = BatchRepository(db)
    batch_repo.create(
        batch_id=batch_id,
        job_id=request.job_id,
        total_candidates=len(ranked),
        chart_paths=chart_paths,
        comparison_table=comparison_table,
    )

    logger.info(f"Batch screening complete: {batch_id}, candidates: {len(ranked)}")

    return BatchScreeningResult(
        batch_id=batch_id,
        job_title=job_record.title,
        total_candidates=len(ranked),
        ranked_candidates=ranked,
        comparison_table=comparison_table,
        chart_paths=chart_paths,
    )


@router.get("/results/{analysis_id}", response_model=ScreeningResult)
async def get_result(analysis_id: str, db: Session = Depends(get_db)):
    """Retrieve a screening result by analysis ID."""
    analysis_repo = AnalysisRepository(db)
    record = analysis_repo.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Analysis not found: {analysis_id}")

    return ScreeningResult(
        analysis_id=record.id,
        candidate_name=record.candidate_name,
        overall_score=record.overall_score,
        recommendation=record.recommendation,
        section_scores=SectionScores(**record.section_scores),
        skill_match=SkillMatchDetail(**record.skill_match),
        strengths=record.strengths or [],
        gaps=record.gaps or [],
        llm_insights=record.llm_insights,
    )


@router.get("/results/{analysis_id}/report")
async def get_report(analysis_id: str, db: Session = Depends(get_db)):
    """Get a formatted text report for a screening result."""
    analysis_repo = AnalysisRepository(db)
    record = analysis_repo.get(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Analysis not found: {analysis_id}")

    job_repo = JobRepository(db)
    job_record = job_repo.get(record.job_id)
    job_title = job_record.title if job_record else ""

    result = ScreeningResult(
        analysis_id=record.id,
        candidate_name=record.candidate_name,
        overall_score=record.overall_score,
        recommendation=record.recommendation,
        section_scores=SectionScores(**record.section_scores),
        skill_match=SkillMatchDetail(**record.skill_match),
        strengths=record.strengths or [],
        gaps=record.gaps or [],
        llm_insights=record.llm_insights,
    )

    report_text = format_single_report(result, job_title)
    return {"analysis_id": analysis_id, "report": report_text}
