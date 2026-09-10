"""
Telegram Platform Adapter
Handles Telegram Bot API communication only.
All AI logic lives in screening_service, scoring_engine, ranking_service.
"""
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.storage.repositories import ConversationStateRepository, JobRepository, ResumeRepository
from app.models.screening import PlatformMessage
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/integrations/telegram", tags=["Telegram"])
logger = get_logger(__name__)
settings = get_settings()

# Conversation states
STATE_IDLE = "idle"
STATE_AWAITING_JD = "awaiting_jd"
STATE_AWAITING_RESUMES = "awaiting_resumes"
STATE_PROCESSING = "processing"


async def send_telegram_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to a Telegram chat via Bot API."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured")
        return False
    try:
        import httpx
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }, timeout=15)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram send message failed: {type(e).__name__}")
        return False


async def send_telegram_photo(chat_id: str, photo_path: str, caption: str = "") -> bool:
    """Send a photo to a Telegram chat."""
    if not settings.telegram_bot_token:
        return False
    try:
        import httpx
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto"
        async with httpx.AsyncClient() as client:
            with open(photo_path, "rb") as f:
                resp = await client.post(url, data={"chat_id": chat_id, "caption": caption},
                                         files={"photo": f}, timeout=30)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram send photo failed: {type(e).__name__}")
        return False


async def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Download a file from Telegram servers."""
    if not settings.telegram_bot_token:
        return None
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            # Get file path
            r = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                params={"file_id": file_id},
                timeout=15,
            )
            file_path = r.json()["result"]["file_path"]
            # Download
            r2 = await client.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
                timeout=30,
            )
            return r2.content
    except Exception as e:
        logger.error(f"Telegram file download failed: {type(e).__name__}")
        return None


@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Telegram webhook endpoint.
    Receives updates from Telegram and handles conversation flow.

    Configure this in BotFather:
    /setwebhook https://your-domain.com/integrations/telegram/webhook
    """
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract message
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}  # Ignore non-message updates

    chat_id = str(message["chat"]["id"])
    user_id = str(message["from"]["id"])
    text = message.get("text", "").strip()
    document = message.get("document")

    state_repo = ConversationStateRepository(db)
    conv = state_repo.get_or_create("telegram", user_id)
    current_state = conv.state

    # ── Handle commands ──
    if text.startswith("/start") or text.startswith("/help"):
        await send_telegram_message(chat_id,
            "👋 *Welcome to Resume Screening Bot!*\n\n"
            "Commands:\n"
            "• /analyze — Start resume screening\n"
            "• /reset — Reset conversation\n"
            "• /help — Show this message\n\n"
            "⚠️ This is an AI-assisted tool, not an autonomous hiring system."
        )
        return {"ok": True}

    if text.startswith("/reset"):
        state_repo.reset("telegram", user_id)
        await send_telegram_message(chat_id, "✅ Conversation reset. Use /analyze to start.")
        return {"ok": True}

    if text.startswith("/analyze"):
        state_repo.update("telegram", user_id, state=STATE_AWAITING_JD, job_id=None, resume_ids=[])
        await send_telegram_message(chat_id,
            "📋 *Resume Screening Started*\n\n"
            "Please paste the *Job Description* text now."
        )
        return {"ok": True}

    # ── State machine ──
    if current_state == STATE_AWAITING_JD and text and not text.startswith("/"):
        # Parse JD
        from app.services.jd_parser import parse_job_description
        from app.storage.repositories import JobRepository
        import uuid

        parsed_jd = parse_job_description(text)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        JobRepository(db).create(job_id, parsed_jd.job_title or "Unnamed Position", text, parsed_jd.model_dump())

        state_repo.update("telegram", user_id, state=STATE_AWAITING_RESUMES, job_id=job_id, resume_ids=[])
        await send_telegram_message(chat_id,
            f"✅ *Job Description received!*\n"
            f"📌 Role: {parsed_jd.job_title}\n"
            f"🔑 Required skills: {', '.join(parsed_jd.required_skills[:5])}\n\n"
            "📎 Now send me *one or more resume files* (PDF or DOCX).\n"
            "Send /screen when done uploading."
        )
        return {"ok": True}

    if current_state == STATE_AWAITING_RESUMES:
        if document:
            # Handle file upload
            file_name = document.get("file_name", "resume.pdf")
            file_id = document["file_id"]
            file_bytes = await download_telegram_file(file_id)

            if file_bytes:
                from app.utils.file_utils import validate_file_extension, save_temp_file, delete_temp_file, get_safe_filename
                from app.services.resume_parser import parse_resume
                import uuid

                safe_name = get_safe_filename(file_name)
                if not validate_file_extension(safe_name):
                    await send_telegram_message(chat_id, "❌ Unsupported file type. Send PDF or DOCX.")
                    return {"ok": True}

                temp_path = save_temp_file(file_bytes, safe_name)
                try:
                    parsed_resume = parse_resume(temp_path)
                    resume_id = f"res_{uuid.uuid4().hex[:12]}"
                    ResumeRepository(db).create(
                        resume_id=resume_id,
                        filename=safe_name,
                        candidate_name=parsed_resume.name,
                        email=parsed_resume.email,
                        phone=parsed_resume.phone,
                        parsed_data=parsed_resume.model_dump(exclude={"raw_text"}),
                    )
                    resume_ids = list(conv.resume_ids or []) + [resume_id]
                    state_repo.update("telegram", user_id, resume_ids=resume_ids)
                    await send_telegram_message(chat_id,
                        f"✅ Resume received: *{parsed_resume.name}*\n"
                        f"Skills found: {len(parsed_resume.skills)}\n\n"
                        "Send more resumes or type /screen to analyze."
                    )
                except Exception as e:
                    await send_telegram_message(chat_id, f"❌ Failed to parse resume. Please try again.")
                finally:
                    delete_temp_file(temp_path)
            return {"ok": True}

        if text.startswith("/screen"):
            resume_ids = list(conv.resume_ids or [])
            if not resume_ids:
                await send_telegram_message(chat_id, "❌ No resumes uploaded yet. Please upload resumes first.")
                return {"ok": True}

            job_id = conv.job_id
            await send_telegram_message(chat_id, f"⏳ Analyzing {len(resume_ids)} resume(s)...")
            state_repo.update("telegram", user_id, state=STATE_PROCESSING)

            try:
                from app.api.routes.screening import screen_single, screen_batch
                from app.models.screening import ScreenRequest, BatchScreenRequest
                from app.services.report_service import generate_telegram_summary, format_batch_report

                if len(resume_ids) == 1:
                    from app.services.scoring_engine import screen_resume
                    from app.models.resume import ParsedResume
                    from app.models.job import ParsedJobDescription

                    job_record = JobRepository(db).get(job_id)
                    resume_record = ResumeRepository(db).get(resume_ids[0])
                    jd = ParsedJobDescription(**job_record.parsed_data)
                    pd_data = dict(resume_record.parsed_data)
                    pd_data["raw_text"] = ""
                    resume = ParsedResume(**pd_data)

                    section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
                    from app.models.screening import ScreeningResult
                    from app.core.config import get_settings
                    settings_inst = get_settings()
                    result = ScreeningResult(
                        analysis_id="telegram_result",
                        candidate_name=resume.name,
                        overall_score=overall_score,
                        recommendation=settings_inst.get_score_category(overall_score),
                        section_scores=section_scores,
                        skill_match=skill_detail,
                        strengths=strengths,
                        gaps=gaps,
                    )
                    summary = generate_telegram_summary(result)
                    await send_telegram_message(chat_id, summary)
                else:
                    # Batch
                    from app.services.scoring_engine import screen_resume
                    from app.models.resume import ParsedResume
                    from app.models.job import ParsedJobDescription
                    from app.services.ranking_service import rank_candidates, build_comparison_table
                    from app.models.screening import BatchScreeningResult
                    from app.utils.chart_utils import generate_overall_score_chart

                    job_record = JobRepository(db).get(job_id)
                    jd = ParsedJobDescription(**job_record.parsed_data)
                    resume_records = ResumeRepository(db).get_many(resume_ids)

                    candidate_results = []
                    for rr in resume_records:
                        pd_data = dict(rr.parsed_data)
                        pd_data["raw_text"] = ""
                        resume = ParsedResume(**pd_data)
                        section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
                        candidate_results.append({
                            "name": resume.name,
                            "analysis_id": f"tg_{resume.name[:6]}",
                            "overall_score": overall_score,
                            "section_scores": section_scores,
                            "skill_match": skill_detail,
                        })

                    ranked = rank_candidates(candidate_results)
                    comparison_table = build_comparison_table(ranked)
                    batch_result = BatchScreeningResult(
                        batch_id="telegram_batch",
                        job_title=job_record.title,
                        total_candidates=len(ranked),
                        ranked_candidates=ranked,
                        comparison_table=comparison_table,
                    )

                    report = format_batch_report(batch_result, job_record.title)
                    await send_telegram_message(chat_id, f"```\n{report[:3800]}\n```", parse_mode="Markdown")

                    # Try to send chart
                    try:
                        score_data = [{"name": rc.candidate_name, "score": rc.overall_score} for rc in ranked]
                        chart_path = generate_overall_score_chart(score_data, job_record.title)
                        await send_telegram_photo(chat_id, chart_path, "Resume Ranking Chart")
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Telegram screening failed: {type(e).__name__}: {e}")
                await send_telegram_message(chat_id, "❌ Analysis failed. Please try again with /reset.")

            state_repo.reset("telegram", user_id)
            return {"ok": True}

    # Default
    if current_state == STATE_IDLE:
        await send_telegram_message(chat_id,
            "Use /analyze to start resume screening, or /help for instructions."
        )

    return {"ok": True}
