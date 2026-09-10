"""Simple Telegram adapter for the resume screening showcase."""
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.job import ParsedJobDescription
from app.models.resume import ParsedResume
from app.services.jd_parser import parse_job_description
from app.services.resume_parser import parse_resume
from app.services.scoring_engine import screen_resume
from app.storage.database import get_db
from app.storage.repositories import ConversationStateRepository, JobRepository, ResumeRepository
from app.utils.file_utils import delete_temp_file, get_safe_filename, save_temp_file, validate_file_extension

router = APIRouter(prefix="/integrations/telegram", tags=["Telegram"])
logger = get_logger(__name__)
settings = get_settings()

STATE_IDLE = "idle"
STATE_AWAITING_JD = "awaiting_jd"
STATE_AWAITING_RESUMES = "awaiting_resumes"
STATE_PROCESSING = "processing"


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """Send a plain Telegram message. Markdown is intentionally avoided for reliability."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=15,
            )
        return response.status_code == 200
    except Exception as exc:
        logger.error(f"Telegram send failed: {type(exc).__name__}")
        return False


async def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Download a Telegram document."""
    if not settings.telegram_bot_token:
        return None
    try:
        async with httpx.AsyncClient() as client:
            file_response = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                params={"file_id": file_id},
                timeout=15,
            )
            file_response.raise_for_status()
            file_path = file_response.json()["result"]["file_path"]
            response = await client.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
                timeout=30,
            )
            response.raise_for_status()
            return response.content
    except Exception as exc:
        logger.error(f"Telegram file download failed: {type(exc).__name__}")
        return None


def format_result(result) -> str:
    """Create the simple, screenshot-friendly Telegram result."""
    scores = result.section_scores
    matched = result.skill_match.matched
    missing = result.skill_match.missing
    return (
        "📄 RESUME SCREENING RESULT\n\n"
        f"Candidate: {result.candidate_name}\n"
        f"Overall Score: {result.overall_score:.1f}/100\n"
        f"Recommendation: {result.recommendation}\n\n"
        "📊 SCORE BREAKDOWN\n"
        f"• Skills Match: {scores.skills:.1f}%\n"
        f"• Experience Match: {scores.experience:.1f}%\n"
        f"• Project Match: {scores.projects:.1f}%\n"
        f"• Education Match: {scores.education:.1f}%\n"
        f"• JD Requirement: {scores.jd_match:.1f}%\n"
        f"• Resume Completeness: {scores.completeness:.1f}%\n\n"
        "✅ MATCHED SKILLS\n"
        f"{', '.join(matched[:10]) if matched else 'None found'}\n\n"
        "❌ MISSING SKILLS\n"
        f"{', '.join(missing[:10]) if missing else 'None'}\n\n"
        "💪 STRENGTHS\n"
        + "\n".join(f"• {item}" for item in result.strengths[:4])
        + "\n\n⚠️ GAPS\n"
        + "\n".join(f"• {item}" for item in result.gaps[:4])
        + "\n\n📌 FINAL RECOMMENDATION\n"
        + result.recommendation
    )


def build_result(resume: ParsedResume, jd: ParsedJobDescription):
    """Run the existing deterministic scoring engine and build its result model."""
    from app.models.screening import ScreeningResult

    section_scores, skill_detail, overall_score, strengths, gaps = screen_resume(resume, jd)
    return ScreeningResult(
        analysis_id=f"telegram_{uuid.uuid4().hex[:8]}",
        candidate_name=resume.name,
        overall_score=overall_score,
        recommendation=settings.get_score_category(overall_score),
        section_scores=section_scores,
        skill_match=skill_detail,
        strengths=strengths,
        gaps=gaps,
    )


@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Telegram updates and run the simple screening flow."""
    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = str(message["chat"]["id"])
    user_id = str(message["from"]["id"])
    text = message.get("text", "").strip()
    document = message.get("document")

    state_repo = ConversationStateRepository(db)
    conv = state_repo.get_or_create("telegram", user_id)
    state = conv.state

    if text.startswith("/start") or text.startswith("/help"):
        await send_telegram_message(
            chat_id,
            "👋 Resume Screening Bot\n\n"
            "/analyze - start screening\n"
            "/screen - analyze uploaded resumes\n"
            "/reset - start over\n\n"
            "Send a job description, then PDF/DOCX resumes."
        )
        return {"ok": True}

    if text.startswith("/reset"):
        state_repo.reset("telegram", user_id)
        await send_telegram_message(chat_id, "✅ Reset complete. Use /analyze to start.")
        return {"ok": True}

    if text.startswith("/analyze"):
        state_repo.update("telegram", user_id, state=STATE_AWAITING_JD, job_id=None, resume_ids=[])
        await send_telegram_message(chat_id, "📋 Send the Job Description text now.")
        return {"ok": True}

    if state == STATE_AWAITING_JD and text and not text.startswith("/"):
        parsed_jd = parse_job_description(text)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        JobRepository(db).create(
            job_id,
            parsed_jd.job_title or "Unnamed Position",
            text,
            parsed_jd.model_dump(),
        )
        state_repo.update(
            "telegram", user_id, state=STATE_AWAITING_RESUMES,
            job_id=job_id, resume_ids=[]
        )
        skills = ", ".join(parsed_jd.required_skills[:8]) or "Not detected"
        await send_telegram_message(
            chat_id,
            f"✅ Job Description received\nRole: {parsed_jd.job_title}\n"
            f"Required skills: {skills}\n\n"
            "📎 Send one or more PDF/DOCX resumes.\n"
            "When finished, send /screen."
        )
        return {"ok": True}

    if state == STATE_AWAITING_RESUMES:
        if document:
            file_name = get_safe_filename(document.get("file_name", "resume.pdf"))
            if not validate_file_extension(file_name):
                await send_telegram_message(chat_id, "❌ Only PDF and DOCX files are supported.")
                return {"ok": True}

            file_bytes = await download_telegram_file(document["file_id"])
            if not file_bytes:
                await send_telegram_message(chat_id, "❌ Could not download the resume. Try again.")
                return {"ok": True}

            temp_path = save_temp_file(file_bytes, file_name)
            try:
                resume = parse_resume(temp_path)
                resume_id = f"res_{uuid.uuid4().hex[:12]}"
                ResumeRepository(db).create(
                    resume_id=resume_id,
                    filename=file_name,
                    candidate_name=resume.name,
                    email=resume.email,
                    phone=resume.phone,
                    parsed_data=resume.model_dump(exclude={"raw_text"}),
                )
                resume_ids = list(conv.resume_ids or []) + [resume_id]
                state_repo.update("telegram", user_id, resume_ids=resume_ids)
                await send_telegram_message(
                    chat_id,
                    f"✅ Resume received: {resume.name}\n"
                    f"Skills found: {len(resume.skills)}\n"
                    "Send another resume or /screen."
                )
            except Exception as exc:
                logger.error(f"Resume parsing failed: {type(exc).__name__}")
                await send_telegram_message(chat_id, "❌ Could not parse this resume. Try another PDF/DOCX.")
            finally:
                delete_temp_file(temp_path)
            return {"ok": True}

        if text.startswith("/screen"):
            resume_ids = list(conv.resume_ids or [])
            if not resume_ids:
                await send_telegram_message(chat_id, "❌ Upload at least one resume first.")
                return {"ok": True}

            state_repo.update("telegram", user_id, state=STATE_PROCESSING)
            await send_telegram_message(chat_id, f"⏳ Screening {len(resume_ids)} resume(s)...")

            try:
                job_record = JobRepository(db).get(conv.job_id)
                jd = ParsedJobDescription(**job_record.parsed_data)
                records = ResumeRepository(db).get_many(resume_ids)
                results = []

                for record in records:
                    data = dict(record.parsed_data)
                    data["raw_text"] = ""
                    results.append(build_result(ParsedResume(**data), jd))

                results.sort(key=lambda item: item.overall_score, reverse=True)
                for rank, result in enumerate(results, start=1):
                    prefix = f"🏆 Rank #{rank}\n\n" if len(results) > 1 else ""
                    await send_telegram_message(chat_id, prefix + format_result(result))
            except Exception as exc:
                logger.error(f"Telegram screening failed: {type(exc).__name__}: {exc}")
                await send_telegram_message(chat_id, "❌ Analysis failed. Use /reset and try again.")

            state_repo.reset("telegram", user_id)
            return {"ok": True}

    if state == STATE_IDLE:
        await send_telegram_message(chat_id, "Use /analyze to start resume screening.")

    return {"ok": True}
